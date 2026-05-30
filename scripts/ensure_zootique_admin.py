"""Ensure a Zootique Super Admin user exists.

Why this exists:
- There is no public registration flow for the `zootique_admin` role.
- On a fresh Postgres database, Zootique Admin login will fail until at least
  one user with role `zootique_admin` exists.

Usage:
  python scripts/ensure_zootique_admin.py --email admin@example.com --password "change-me" --full-name "Super Admin"

If you omit --password, a secure temporary password will be generated and printed.

Requires:
- DATABASE_URL in environment (.env is supported)
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from models import User, db  # noqa: E402


PASSWORD_MIN_LENGTH = 8


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/ensure a zootique_admin user exists.")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--full-name", default="Super Admin", help="Admin display name")
    parser.add_argument("--username", default=None, help="Optional username")
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password (min 8 chars). If omitted, a secure temporary password is generated.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="If the user already exists, reset its password to --password (or generated password).",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(override=True)
    args = _parse_args()

    email = (args.email or "").strip().lower()
    if not email:
        raise SystemExit("--email is required")

    password = args.password
    generated_password = None
    if not password:
        generated_password = secrets.token_urlsafe(12)
        password = generated_password

    if len(password) < PASSWORD_MIN_LENGTH:
        raise SystemExit(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email, role="zootique_admin").first()

        if user:
            user.full_name = args.full_name or user.full_name
            if args.username is not None:
                user.username = (args.username or "").strip() or None

            if args.reset_password or generated_password:
                user.set_password(password)

            db.session.commit()
            action = "updated" if (args.reset_password or args.username is not None or args.full_name) else "exists"
        else:
            user = User(email=email, full_name=args.full_name, role="zootique_admin", status="active")
            if args.username:
                user.username = (args.username or "").strip() or None
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            action = "created"

    print(f"Zootique admin user {action}: {email}")
    if generated_password:
        print(f"Temporary password: {generated_password}")
    print("Login at: /auth/login/zootique_admin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
