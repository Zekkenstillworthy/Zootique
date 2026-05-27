import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


DEFAULT_DEMO_EMAILS = [
    "admin@zootique.com",
    "staff1_1@manilazoo.com",
    "visitor1@gmail.com",
    "admin1@lygerzoo.com",
]


def _parse_created_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow()

    s = str(value).strip()
    if not s:
        return datetime.utcnow()

    # Common SQLite timestamp formats are ISO-ish; be forgiving.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()


def _load_sqlite_users(sqlite_path: Path, emails: list[str] | None, load_all: bool) -> list[dict]:
    con = sqlite3.connect(str(sqlite_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if load_all:
        cur.execute(
            "select id, email, username, password_hash, role, full_name, zoo_id, status, profile_image, created_at from users"
        )
    else:
        if not emails:
            emails = DEFAULT_DEMO_EMAILS
        placeholders = ",".join(["?"] * len(emails))
        cur.execute(
            f"select id, email, username, password_hash, role, full_name, zoo_id, status, profile_image, created_at from users where email in ({placeholders})",
            emails,
        )

    rows = [dict(r) for r in cur.fetchall()]

    # Load zoo names for mapping.
    cur.execute("select id, name from zoos")
    sqlite_zoos = {int(r[0]): str(r[1]) for r in cur.fetchall()}

    con.close()

    for row in rows:
        zoo_id = row.get("zoo_id")
        if zoo_id is not None:
            row["sqlite_zoo_name"] = sqlite_zoos.get(int(zoo_id))
        else:
            row["sqlite_zoo_name"] = None

    return rows


def _load_postgres_zoos(conn) -> dict[str, int]:
    rows = conn.execute(text("select id, name from zoos")).fetchall()
    return {str(name).strip().lower(): int(zoo_id) for zoo_id, name in rows}


def _map_zoo_id(sqlite_zoo_name: str | None, pg_zoos_by_name: dict[str, int]) -> int | None:
    if not sqlite_zoo_name:
        return None

    normalized = sqlite_zoo_name.strip().lower()
    if normalized in pg_zoos_by_name:
        return pg_zoos_by_name[normalized]

    # Minimal compatibility mapping between known dataset variants.
    fallback_name_map = {
        "lyger": "lyger zoo",
        "lyger safari park": "lyger zoo",
    }

    fallback = fallback_name_map.get(normalized)
    if fallback and fallback in pg_zoos_by_name:
        return pg_zoos_by_name[fallback]

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync users from SQLite zootique.db into Postgres by email.")
    parser.add_argument(
        "--sqlite-path",
        default=str(Path("instance") / "zootique.db"),
        help="Path to SQLite source DB (default: instance/zootique.db)",
    )
    parser.add_argument(
        "--emails",
        default=",".join(DEFAULT_DEMO_EMAILS),
        help="Comma-separated list of emails to sync (ignored if --all)",
    )
    parser.add_argument("--all", action="store_true", help="Sync all users from SQLite")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If a user email already exists in Postgres, overwrite password/role/etc",
    )

    args = parser.parse_args()

    load_dotenv(override=True)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required (Postgres-only mode).")

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    emails = [e.strip() for e in (args.emails or "").split(",") if e.strip()]

    sqlite_users = _load_sqlite_users(sqlite_path, emails, args.all)
    if not sqlite_users:
        print("No matching users found in SQLite.")
        return 0

    engine = create_engine(database_url)

    inserted = 0
    updated = 0
    skipped = 0
    warnings: list[str] = []

    with engine.begin() as conn:
        pg_zoos_by_name = _load_postgres_zoos(conn)

        for u in sqlite_users:
            email = u.get("email")
            if not email:
                skipped += 1
                continue

            # Make sure username uniqueness doesn't block insert.
            username = u.get("username")
            if username:
                existing_username = conn.execute(
                    text("select id, email from users where username = :username"),
                    {"username": username},
                ).fetchone()
                if existing_username and str(existing_username[1]).strip().lower() != str(email).strip().lower():
                    warnings.append(f"username '{username}' already used by {existing_username[1]} — setting username=NULL for {email}")
                    username = None

            pg_zoo_id = _map_zoo_id(u.get("sqlite_zoo_name"), pg_zoos_by_name)
            if u.get("zoo_id") is not None and pg_zoo_id is None:
                warnings.append(
                    f"No Postgres zoo match for SQLite zoo '{u.get('sqlite_zoo_name')}' (email={email}) — setting zoo_id=NULL"
                )

            payload = {
                "email": email,
                "username": username,
                "password_hash": u.get("password_hash"),
                "role": u.get("role") or "visitor",
                "full_name": u.get("full_name"),
                "zoo_id": pg_zoo_id,
                "status": u.get("status") or "active",
                "profile_image": u.get("profile_image"),
                "created_at": _parse_created_at(u.get("created_at")),
            }

            if not payload["password_hash"]:
                warnings.append(f"SQLite user {email} has no password_hash — skipping")
                skipped += 1
                continue

            existing = conn.execute(text("select id from users where email = :email"), {"email": email}).fetchone()
            if existing:
                if args.overwrite:
                    conn.execute(
                        text(
                            """
                            update users
                            set username = :username,
                                password_hash = :password_hash,
                                role = :role,
                                full_name = :full_name,
                                zoo_id = :zoo_id,
                                status = :status,
                                profile_image = :profile_image
                            where email = :email
                            """
                        ),
                        payload,
                    )
                    updated += 1
                else:
                    skipped += 1
                continue

            conn.execute(
                text(
                    """
                    insert into users (email, username, password_hash, role, full_name, zoo_id, status, profile_image, created_at)
                    values (:email, :username, :password_hash, :role, :full_name, :zoo_id, :status, :profile_image, :created_at)
                    """
                ),
                payload,
            )
            inserted += 1

    print(f"Synced users from SQLite -> Postgres. inserted={inserted} updated={updated} skipped={skipped}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
