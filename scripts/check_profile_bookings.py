from pathlib import Path
import sys
from dataclasses import dataclass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app
from models import Zoo, db

VISITOR_EMAIL = "visitor1@gmail.com"
VISITOR_PASSWORD = "Password123"


def main():
    app = create_app()
    with app.app_context():
        client = app.test_client()
        # Login
        resp = client.post(
            "/auth/login/visitor",
            data={"email": VISITOR_EMAIL, "password": VISITOR_PASSWORD, "next": "/visitor/"},
            follow_redirects=False,
        )
        print("Login status:", resp.status_code, "Location:", resp.headers.get("Location"))
        if resp.status_code not in (302, 303):
            print("Login failed; cannot verify profile bookings.")
            return 2

        # Access profile bookings tab
        # If choose-zoo was required, select the first available zoo and continue
        if resp.headers.get("Location", "").startswith("/visitor/choose-zoo"):
            first_zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if first_zoo:
                resp_sel = client.post(
                    "/visitor/choose-zoo",
                    data={"zoo_id": str(first_zoo.id), "next": "/visitor/profile?tab=bookings"},
                    follow_redirects=False,
                )
                print("Choose-zoo post status:", resp_sel.status_code, "Location:", resp_sel.headers.get("Location"))

        resp2 = client.get("/visitor/profile?tab=bookings", follow_redirects=True)
        print("Profile (bookings) GET status:", resp2.status_code)
        body = resp2.get_data(as_text=True)
        found_all = "All Bookings" in body or "No bookings found for this account" in body
        if found_all:
            print("Profile bookings tab rendered. Summary:")
            # Show snippet around "All Bookings"
            idx = body.find("All Bookings")
            start = max(0, idx-200)
            print(body[start:start+500])
            return 0
        else:
            print("Couldn't find bookings block in profile page; response length:", len(body))
            return 3


if __name__ == '__main__':
    raise SystemExit(main())
