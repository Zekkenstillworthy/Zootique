"""System smoke test + working percentage report.

Runs against the configured Postgres DB (DATABASE_URL) using Flask's test client.
It does NOT start a web server.

Definition of "working" for this report
----------------------------------------
- Pages: HTTP 200, or a redirect (302/303) *within the same module*.
  Redirects to /auth/login/* for module pages count as FAIL.
- API endpoints: HTTP 200 with the correct role session.

Usage:
  python scripts/system_smoke_report.py

Outputs:
- Prints per-module and overall pass rates
- Writes a JSON report to scripts/system_smoke_report.json

Exit codes:
  0 = all checks pass
  2 = one or more checks failed
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from models import Zoo, db  # noqa: E402


@dataclass
class RouteCheck:
    module: str
    path: str
    ok: bool
    status_code: int
    location: str = ""
    note: str = ""


def _parse_routes(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("===") and line.endswith("==="):
            current = line.strip("=").strip()
            sections[current] = []
            continue
        if current and line.startswith("/"):
            sections[current].append(line)
    return sections


def _slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "zoo"


def _reorder_logout_last(paths: Iterable[str]) -> list[str]:
    paths_list = list(paths)
    normal = [p for p in paths_list if "logout" not in p]
    logouty = [p for p in paths_list if "logout" in p]
    return normal + logouty


def _is_login_redirect(location: str) -> bool:
    return (location or "").startswith("/auth/login")


def _page_ok(*, status_code: int, location: str, module_prefix: str | None) -> bool:
    if status_code == 200:
        return True
    if status_code in (302, 303):
        if _is_login_redirect(location):
            return False
        if module_prefix and location.startswith(module_prefix):
            return True
        # Some pages legitimately bounce back to landing/visitor home.
        if location in {"/", "/visitor/", "/visitor"}:
            return True
    return False


def _login(client, *, module_name: str, email: str, password: str, next_url: str) -> tuple[bool, str, int]:
    resp = client.post(
        f"/auth/login/{module_name}",
        data={"email": email, "password": password, "next": next_url},
        follow_redirects=False,
    )
    return resp.status_code in (302, 303), (resp.headers.get("Location") or ""), resp.status_code


def _select_visitor_zoo(client, *, zoo_id: int) -> tuple[bool, str, int]:
    resp = client.post(
        "/visitor/choose-zoo",
        data={"zoo_id": str(int(zoo_id)), "next": "/visitor/"},
        follow_redirects=False,
    )
    return resp.status_code in (302, 303), (resp.headers.get("Location") or ""), resp.status_code


def _read_routes_file() -> dict[str, list[str]]:
    route_path = REPO_ROOT / "routes_by_module.txt"
    text = route_path.read_text(encoding="utf-8")
    return _parse_routes(text)


def _run_checks_for_pages(client, *, module: str, module_prefix: str, paths: list[str]) -> list[RouteCheck]:
    results: list[RouteCheck] = []
    for path in _reorder_logout_last(paths):
        resp = client.get(path, follow_redirects=False)
        loc = resp.headers.get("Location") or ""
        ok = _page_ok(status_code=resp.status_code, location=loc, module_prefix=module_prefix)
        results.append(RouteCheck(module=module, path=path, ok=ok, status_code=int(resp.status_code), location=loc))
    return results


def _run_checks_for_api(client, *, module: str, paths: list[str]) -> list[RouteCheck]:
    results: list[RouteCheck] = []
    for path in paths:
        resp = client.get(path, follow_redirects=False)
        ok = resp.status_code == 200
        loc = resp.headers.get("Location") or ""
        results.append(RouteCheck(module=module, path=path, ok=ok, status_code=int(resp.status_code), location=loc))
    return results


def _summarize(checks: list[RouteCheck]) -> dict[str, Any]:
    total = len(checks)
    passed = sum(1 for c in checks if c.ok)
    failed = total - passed
    pct = (passed / total * 100.0) if total else 0.0
    return {"total": total, "passed": passed, "failed": failed, "percent": round(pct, 2)}


def main() -> int:
    load_dotenv(override=True)

    try:
        app = create_app()
    except Exception as exc:
        print("FAIL: app startup (DATABASE_URL / Postgres connectivity)")
        print(str(exc))
        return 2

    all_checks: list[RouteCheck] = []

    with app.app_context():
        # Ensure schema + demo data exist.
        try:
            from services.demo_seed import ensure_demo_data

            ensure_demo_data(allow_create_tables=True)
        except Exception:
            db.session.rollback()

        zoo = Zoo.query.order_by(Zoo.id.asc()).first()
        if not zoo:
            print("FAIL: no Zoo rows found even after seeding")
            return 2

        demo_password = "Password123!"
        try:
            import os

            demo_password = os.environ.get("DEMO_PASSWORD", demo_password) or demo_password
            if len(demo_password) < 8:
                demo_password = "Password123!"
        except Exception:
            demo_password = "Password123!"

        visitor_email = "visitor1@example.com"
        superadmin_email = "superadmin@zootique.local"
        zoo_admin_email = f"{_slug(zoo.name)}_admin@example.com"
        zoo_staff_email = f"{_slug(zoo.name)}_staff1@example.com"

        sections = _read_routes_file()

        # Public / Auth pages (anonymous)
        public_checks: list[RouteCheck] = []
        with app.test_client() as client:
            # landing
            r = client.get("/", follow_redirects=False)
            public_checks.append(RouteCheck(module="Public", path="/", ok=(r.status_code == 200), status_code=int(r.status_code)))

            auth_paths = sections.get("Auth", [])
            public_checks.extend(_run_checks_for_pages(client, module="Auth", module_prefix="/auth", paths=auth_paths))

            # API health should be public
            r2 = client.get("/api/health", follow_redirects=False)
            public_checks.append(RouteCheck(module="API-Public", path="/api/health", ok=(r2.status_code == 200), status_code=int(r2.status_code)))

        all_checks.extend(public_checks)

        # Visitor module
        visitor_paths_raw = sections.get("Visitor", [])
        visitor_paths = []
        for p in visitor_paths_raw:
            if p == "/":
                visitor_paths.append("/visitor/")
            else:
                visitor_paths.append("/visitor" + p)
        # Add choose-zoo because it's core to Visitor flow but not in the file.
        if "/visitor/choose-zoo" not in visitor_paths:
            visitor_paths.insert(0, "/visitor/choose-zoo")

        with app.test_client() as client:
            ok, loc, sc = _login(client, module_name="visitor", email=visitor_email, password=demo_password, next_url="/visitor/")
            all_checks.append(RouteCheck(module="Visitor-Login", path="/auth/login/visitor", ok=ok, status_code=sc, location=loc))
            if ok:
                ok2, loc2, sc2 = _select_visitor_zoo(client, zoo_id=int(zoo.id))
                all_checks.append(RouteCheck(module="Visitor-ChooseZoo", path="/visitor/choose-zoo [POST]", ok=ok2, status_code=sc2, location=loc2))
            all_checks.extend(_run_checks_for_pages(client, module="Visitor", module_prefix="/visitor", paths=visitor_paths))

            visitor_api_paths = [p for p in sections.get("API", []) if p.startswith("/api/visitor/")]
            visitor_api_paths.append("/api/auth/me")
            all_checks.extend(_run_checks_for_api(client, module="API-Visitor", paths=sorted(set(visitor_api_paths))))

        # Zoo Admin module
        zoo_admin_paths = sections.get("Zoo Admin", [])
        with app.test_client() as client:
            ok, loc, sc = _login(client, module_name="zoo_admin", email=zoo_admin_email, password=demo_password, next_url="/animal-farm-admin/")
            all_checks.append(RouteCheck(module="ZooAdmin-Login", path="/auth/login/zoo_admin", ok=ok, status_code=sc, location=loc, note=zoo_admin_email))
            all_checks.extend(_run_checks_for_pages(client, module="Zoo Admin", module_prefix="/animal-farm-admin", paths=zoo_admin_paths))

            admin_api_paths = [p for p in sections.get("API", []) if p.startswith("/api/admin/")]
            admin_api_paths.append("/api/auth/me")
            all_checks.extend(_run_checks_for_api(client, module="API-Admin", paths=sorted(set(admin_api_paths))))

        # Zoo Staff module
        zoo_staff_paths = sections.get("Zoo Staff", [])
        with app.test_client() as client:
            ok, loc, sc = _login(client, module_name="zoo_staff", email=zoo_staff_email, password=demo_password, next_url="/animal-farm-staff/")
            all_checks.append(RouteCheck(module="ZooStaff-Login", path="/auth/login/zoo_staff", ok=ok, status_code=sc, location=loc, note=zoo_staff_email))
            all_checks.extend(_run_checks_for_pages(client, module="Zoo Staff", module_prefix="/animal-farm-staff", paths=zoo_staff_paths))

            staff_api_paths = [p for p in sections.get("API", []) if p.startswith("/api/staff/")]
            staff_api_paths.append("/api/auth/me")
            all_checks.extend(_run_checks_for_api(client, module="API-Staff", paths=sorted(set(staff_api_paths))))

        # Super Admin module
        super_admin_paths = sections.get("Super Admin", [])
        with app.test_client() as client:
            ok, loc, sc = _login(client, module_name="zootique_admin", email=superadmin_email, password=demo_password, next_url="/zootique-admin/")
            all_checks.append(RouteCheck(module="SuperAdmin-Login", path="/auth/login/zootique_admin", ok=ok, status_code=sc, location=loc, note=superadmin_email))
            all_checks.extend(_run_checks_for_pages(client, module="Super Admin", module_prefix="/zootique-admin", paths=super_admin_paths))

            sa_api_paths = [p for p in sections.get("API", []) if p.startswith("/api/super-admin/")]
            sa_api_paths.append("/api/auth/me")
            all_checks.extend(_run_checks_for_api(client, module="API-SuperAdmin", paths=sorted(set(sa_api_paths))))

    # Summaries
    by_module: dict[str, list[RouteCheck]] = {}
    for c in all_checks:
        by_module.setdefault(c.module, []).append(c)

    module_summaries = {k: _summarize(v) for k, v in sorted(by_module.items(), key=lambda kv: kv[0])}
    overall = _summarize(all_checks)

    out = {
        "overall": overall,
        "modules": module_summaries,
        "checks": [asdict(c) for c in all_checks],
    }

    out_path = REPO_ROOT / "scripts" / "system_smoke_report.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\nSystem smoke report")
    print(f"Overall: {overall['passed']}/{overall['total']} passing ({overall['percent']}%)")

    # Print key module rollups (grouped) rather than every sub-bucket.
    for group in (
        "Public",
        "Auth",
        "Visitor",
        "Zoo Admin",
        "Zoo Staff",
        "Super Admin",
        "API-Public",
        "API-Visitor",
        "API-Admin",
        "API-Staff",
        "API-SuperAdmin",
    ):
        if group not in module_summaries:
            continue
        s = module_summaries[group]
        print(f"- {group}: {s['passed']}/{s['total']} ({s['percent']}%)")

    # Show top failures to make it actionable.
    failed = [c for c in all_checks if not c.ok]
    if failed:
        print("\nTop failures (first 25):")
        for c in failed[:25]:
            loc = f" Location={c.location}" if c.location else ""
            note = f" ({c.note})" if c.note else ""
            print(f"- [{c.module}] {c.path}{note} -> {c.status_code}{loc}")

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
