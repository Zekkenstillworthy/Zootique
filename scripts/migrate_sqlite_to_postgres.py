import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import models


def _default_sqlite_path() -> Path:
    # Default to repo-local instance/zootique.db
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "instance" / "zootique.db"


def _normalize_postgres_url(database_url: str) -> str:
    database_url = (database_url or "").strip()
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    return database_url


def _chunked(items, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _find_pg_dump() -> str | None:
    # 1) Explicit override
    explicit = (os.environ.get("PG_DUMP") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p)

    # 2) PATH lookup
    from_path = shutil.which("pg_dump")
    if from_path:
        return from_path

    # 3) Windows fallback (common default install location)
    if os.name == "nt":
        base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
        if base.exists():
            candidates = list(base.glob("*/bin/pg_dump.exe"))

            def ver_key(p: Path):
                # parent.parent is version dir (e.g., ...\PostgreSQL\17\bin\pg_dump.exe)
                name = p.parent.parent.name
                try:
                    return int(name)
                except Exception:
                    return -1

            if candidates:
                candidates.sort(key=ver_key, reverse=True)
                return str(candidates[0])

    return None


def _pg_dump(database_url: str, out_path: Path) -> bool:
    pg_dump = _find_pg_dump()
    if not pg_dump:
        print("pg_dump not found on PATH; skipping Postgres dump.")
        print(
            "If you have PostgreSQL client tools installed, you can run: "
            f"pg_dump --dbname \"{database_url}\" -f \"{out_path}\""
        )
        print("Tip (Windows): set PG_DUMP to your pg_dump.exe path, e.g. PG_DUMP=C:\\Program Files\\PostgreSQL\\17\\bin\\pg_dump.exe")
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        pg_dump,
        "--dbname",
        database_url,
        "--no-owner",
        "--no-privileges",
        "--format",
        "p",
        "-f",
        str(out_path),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"pg_dump failed with exit code {result.returncode}.")
        return False

    print(f"Wrote Postgres dump to: {out_path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate instance/zootique.db (SQLite) data into Postgres.")
    parser.add_argument(
        "--sqlite",
        dest="sqlite_path",
        default=str(_default_sqlite_path()),
        help="Path to SQLite database file (default: instance/zootique.db)",
    )
    parser.add_argument(
        "--postgres-url",
        dest="postgres_url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres SQLAlchemy URL. Defaults to env DATABASE_URL.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create tables in Postgres from models before importing.",
    )
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="TRUNCATE all known tables in Postgres before importing (DANGEROUS).",
    )
    parser.add_argument(
        "--dump",
        dest="dump_path",
        default="",
        help="Optional path to write a Postgres SQL dump (uses pg_dump if available).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Insert batch size (default: 1000)",
    )

    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    postgres_url = _normalize_postgres_url(args.postgres_url)
    if not postgres_url or not postgres_url.startswith("postgresql"):
        raise SystemExit(
            "Postgres URL required. Set DATABASE_URL to something like postgresql+psycopg://user:pass@host:5432/dbname"
        )

    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    print(f"SQLite source:   {sqlite_path}")
    print(f"Postgres target: {postgres_url}")

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(postgres_url)

    target_md = models.db.metadata

    if args.create_schema:
        print("Creating schema in Postgres from models...")
        target_md.create_all(bind=pg_engine)

    # Reflect source SQLite schema
    source_md = MetaData()
    source_md.reflect(bind=sqlite_engine)

    target_tables = list(target_md.sorted_tables)

    with pg_engine.begin() as pg_conn:
        # Optional safety reset
        if args.truncate_first:
            print("Truncating Postgres tables...")
            for table in reversed(target_tables):
                pg_conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))

        with sqlite_engine.connect() as sqlite_conn:
            for table in target_tables:
                source_table = source_md.tables.get(table.name)
                if source_table is None:
                    continue
                source_cols = {c.name for c in source_table.columns}
                common_cols = [c for c in table.columns if c.name in source_cols]

                if not common_cols:
                    continue

                pk_cols = [c.name for c in table.primary_key.columns]

                rows = sqlite_conn.execute(select(*[source_table.c[c.name] for c in common_cols])).mappings().all()
                if not rows:
                    continue

                print(f"Importing {len(rows)} rows into {table.name}...")

                for batch in _chunked(rows, max(1, args.batch_size)):
                    payload = [{c.name: r.get(c.name) for c in common_cols} for r in batch]

                    if pk_cols:
                        stmt = pg_insert(table).values(payload)
                        stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
                    else:
                        stmt = table.insert().values(payload)

                    pg_conn.execute(stmt)

            # Fix sequences for integer PKs (best-effort)
            for table in target_tables:
                pk = list(table.primary_key.columns)
                if len(pk) != 1:
                    continue
                pk_col = pk[0]
                if str(pk_col.type).lower() not in {"integer", "bigint"}:
                    continue

                # pg_get_serial_sequence returns NULL for identity/non-serial columns.
                pg_conn.execute(
                    text(
                        f"""
                        WITH seq AS (
                            SELECT pg_get_serial_sequence(:table_name, :col_name) AS seq_name
                        )
                        SELECT setval(
                            seq.seq_name,
                            GREATEST((SELECT COALESCE(MAX(\"{pk_col.name}\"), 1) FROM \"{table.name}\"), 1)
                        )
                        FROM seq
                        WHERE seq.seq_name IS NOT NULL
                        """
                    ),
                    {"table_name": table.name, "col_name": pk_col.name},
                )

    if args.dump_path:
        dump_path = Path(args.dump_path)
    else:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dump_path = Path(__file__).resolve().parents[1] / "backups" / f"zootique_postgres_{ts}.sql"

    _pg_dump(postgres_url, dump_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
