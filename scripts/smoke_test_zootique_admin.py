"""Smoke test the Zootique Admin module end-to-end.

This runs against your configured Postgres database (DATABASE_URL) using
Flask's test client. It does NOT start a web server.

What it verifies:
- Can create/ensure a zootique_admin user exists
- Can log in as zootique_admin
- Can load key admin pages (dashboard, subscriptions, feedback, reports, user-management, settings)
- Can create/toggle/reset/delete a zoo_admin user via User Management
- Logout clears session and protected routes redirect back to login

Usage:
  python scripts/smoke_test_zootique_admin.py

Optional args:
  --admin-email, --admin-password (if omitted, a temporary admin will be created)

Exit codes:
  0 = PASS
  2 = FAIL
"""

from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from models import User, Zoo, db  # noqa: E402


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke test Zootique Admin")
    p.add_argument("--admin-email", default=None)
    p.add_argument("--admin-password", default=None)
    return p.parse_args()


def _ensure_min_data() -> None:
    """Ensure required tables and at least one Zoo exist."""
    db.create_all()

    zoo = Zoo.query.order_by(Zoo.id.asc()).first()
    if not zoo:
        zoo = Zoo(
            name="Smoke Test Zoo",
            type="Zoo Park",
            location="Test",
            description="Created by smoke tests",
            image_url=None,
        )
        db.session.add(zoo)
        db.session.commit()


def _ensure_admin(email: str | None, password: str | None) -> tuple[str, str, bool]:
    created_temp = False

    if not email:
        email = f"sa_smoketest_{secrets.token_hex(6)}@example.com"

    if not password:
        password = secrets.token_urlsafe(12)
        created_temp = True

    email = email.strip().lower()

    user = User.query.filter_by(email=email, role="zootique_admin").first()
    if user:
        user.status = "active"
        user.set_password(password)
        if not user.full_name:
            user.full_name = "Smoke Test Super Admin"
        db.session.commit()
        return email, password, created_temp

    user = User(email=email, full_name="Smoke Test Super Admin", role="zootique_admin", status="active")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return email, password, created_temp


def _login(client, email: str, password: str) -> CheckResult:
    resp = client.post(
        "/auth/login/zootique_admin",
        data={"email": email, "password": password, "next": "/zootique-admin/"},
        follow_redirects=False,
    )

    if resp.status_code not in (302, 303):
        return CheckResult("login", False, f"Expected redirect, got {resp.status_code}")

    location = resp.headers.get("Location", "")
    if not location.startswith("/zootique-admin"):
        return CheckResult("login", False, f"Unexpected redirect Location: {location}")

    return CheckResult("login", True)


def _get_ok(client, path: str) -> CheckResult:
    resp = client.get(path, follow_redirects=False)
    if resp.status_code != 200:
        loc = resp.headers.get("Location", "")
        return CheckResult(f"GET {path}", False, f"{resp.status_code} Location={loc}")
    return CheckResult(f"GET {path}", True)


def _user_mgmt_crud(client) -> list[CheckResult]:
    results: list[CheckResult] = []

    new_email = f"zoo_admin_{secrets.token_hex(6)}@example.com"
    new_password = "TestPassw0rd!"

    resp = client.post(
        "/zootique-admin/user-management/users/save",
        data={
            "full_name": "Smoke Zoo Admin",
            "email": new_email,
            "status": "active",
            "password": new_password,
            "zoo_id": "",
        },
        follow_redirects=False,
    )
    if resp.status_code not in (302, 303):
        results.append(CheckResult("create zoo_admin", False, f"Expected redirect, got {resp.status_code}"))
        return results

    created = User.query.filter_by(email=new_email, role="zoo_admin").first()
    if not created:
        results.append(CheckResult("create zoo_admin", False, "User not found after save"))
        return results

    results.append(CheckResult("create zoo_admin", True))

    resp = client.post(f"/zootique-admin/user-management/users/{created.id}/toggle-status", follow_redirects=False)
    if resp.status_code not in (302, 303):
        results.append(CheckResult("toggle status", False, f"{resp.status_code}"))
    else:
        db.session.refresh(created)
        results.append(CheckResult("toggle status", True, f"status={created.status}"))

    resp = client.post(f"/zootique-admin/user-management/users/{created.id}/reset-password", follow_redirects=False)
    if resp.status_code not in (302, 303):
        results.append(CheckResult("reset password", False, f"{resp.status_code}"))
    else:
        results.append(CheckResult("reset password", True))

    resp = client.post(f"/zootique-admin/user-management/users/{created.id}/delete", follow_redirects=False)
    if resp.status_code not in (302, 303):
        results.append(CheckResult("delete user", False, f"{resp.status_code}"))
    else:
        deleted = db.session.get(User, created.id)
        results.append(CheckResult("delete user", deleted is None, "" if deleted is None else "Still exists"))

    return results


def _logout_and_redirect(client) -> list[CheckResult]:
    results: list[CheckResult] = []

    resp = client.get("/auth/logout", follow_redirects=False)
    if resp.status_code not in (302, 303):
        results.append(CheckResult("logout", False, f"{resp.status_code}"))
        return results

    # Protected route should redirect back to module login with next.
    resp2 = client.get("/zootique-admin/", follow_redirects=False)
    if resp2.status_code not in (302, 303):
        results.append(CheckResult("post-logout redirect", False, f"Expected redirect, got {resp2.status_code}"))
        return results

    location = resp2.headers.get("Location", "")
    if not location.startswith("/auth/login/zootique_admin"):
        results.append(CheckResult("post-logout redirect", False, f"Unexpected Location={location}"))
    else:
        results.append(CheckResult("post-logout redirect", True, f"Location={location}"))

    return results


def main() -> int:
    load_dotenv(override=True)
    args = _args()

    checks: list[CheckResult] = []

    try:
        app = create_app()
    except Exception as exc:
        print("FAIL: app startup (DATABASE_URL / Postgres connectivity)")
        print(str(exc))
        return 2

    with app.app_context():
        try:
            _ensure_min_data()
        except Exception as exc:
            print("FAIL: ensure schema/min data")
            print(str(exc))
            return 2

        admin_email, admin_password, temp = _ensure_admin(args.admin_email, args.admin_password)

        with app.test_client() as client:
            checks.append(_login(client, admin_email, admin_password))

            # Key pages
            for path in (
                "/zootique-admin/",
                "/zootique-admin/subscriptions",
                "/zootique-admin/zoo-feedback",
                "/zootique-admin/reports",
                "/zootique-admin/user-management",
                "/zootique-admin/settings",
            ):
                checks.append(_get_ok(client, path))

            # User management actions
            checks.extend(_user_mgmt_crud(client))

            # Logout redirect
            checks.extend(_logout_and_redirect(client))

    failed = [c for c in checks if not c.ok]

    print("\nZootique Admin smoke test")
    print(f"Admin: {admin_email}{' (temporary)' if temp else ''}")
    if temp:
        print(f"Temp password: {admin_password}")

    for c in checks:
        status = "PASS" if c.ok else "FAIL"
        detail = f" — {c.detail}" if c.detail else ""
        print(f"{status}: {c.name}{detail}")

    if failed:
        print(f"\nRESULT: FAIL ({len(failed)} checks)")
        return 2

    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
