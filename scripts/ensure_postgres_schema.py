import os
import sys
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import models


@dataclass
class Change:
    table: str
    action: str
    detail: str


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _type_sql(col: sa.Column, dialect: sa.Dialect) -> str:
    t = col.type
    if isinstance(t, sa.String):
        return f"VARCHAR({t.length})" if getattr(t, "length", None) else "VARCHAR"
    if isinstance(t, sa.Text):
        return "TEXT"
    if isinstance(t, sa.Integer):
        return "INTEGER"
    if isinstance(t, sa.BigInteger):
        return "BIGINT"
    if isinstance(t, sa.Float):
        return "DOUBLE PRECISION"
    if isinstance(t, sa.Boolean):
        return "BOOLEAN"
    if isinstance(t, sa.DateTime):
        return "TIMESTAMP"
    if isinstance(t, sa.Date):
        return "DATE"
    if isinstance(t, sa.Time):
        return "TIME"

    # Fallback to dialect compilation
    return t.compile(dialect=dialect)


def _column_add_ddl(col: sa.Column, dialect: sa.Dialect) -> str:
    col_name = _quote_ident(col.name)
    col_type = _type_sql(col, dialect)

    # Be conservative: add as NULLABLE first to avoid failing on existing rows.
    # We backfill/constraint-enforce only for a tiny set of safe defaults.
    return f"{col_name} {col_type}"


def main() -> int:
    load_dotenv(override=True)

    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = sa.create_engine(database_url)
    insp = sa.inspect(engine)

    changes: list[Change] = []

    metadata = models.db.metadata

    with engine.begin() as conn:
        existing_tables = set(insp.get_table_names(schema="public"))

        # 1) Create missing tables
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                table.create(bind=conn)
                changes.append(Change(table.name, "create_table", "created"))

        # Refresh inspector view after creating tables
        insp2 = sa.inspect(conn)

        # 2) Add missing columns
        for table in metadata.sorted_tables:
            if table.name not in insp2.get_table_names(schema="public"):
                continue

            existing_cols = {c["name"] for c in insp2.get_columns(table.name, schema="public")}
            for col in table.columns:
                if col.name in existing_cols:
                    continue

                ddl = _column_add_ddl(col, conn.dialect)
                conn.execute(sa.text(f"ALTER TABLE {_quote_ident(table.name)} ADD COLUMN {ddl}"))
                changes.append(Change(table.name, "add_column", col.name))

        # 3) Backfill a couple of common columns where safe
        # Users table is needed for login.
        public_tables = set(insp2.get_table_names(schema="public"))
        if "users" in public_tables:
            # created_at: fill NULLs with now()
            user_cols = {c["name"] for c in insp2.get_columns("users", schema="public")}
            if "created_at" in user_cols:
                conn.execute(sa.text('UPDATE "users" SET "created_at" = NOW() WHERE "created_at" IS NULL'))
            if "status" in user_cols:
                conn.execute(sa.text("UPDATE \"users\" SET \"status\" = 'active' WHERE \"status\" IS NULL"))

    if not changes:
        print("No schema changes needed.")
        return 0

    print("Applied schema changes:")
    for ch in changes:
        print(f"- {ch.table}: {ch.action} ({ch.detail})")

    print("\nNext: restart the app (python app.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
