"""Repeatable browser smoke checks for the round-two verification scenarios.

Run with:
    python tests/e2e/round_two_smoke.py
"""

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5000"


def login(page, module, email, password, destination):
    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/auth/login/{module}?next={destination}")
    page.get_by_role("textbox", name="you@example.com").fill(email)
    page.get_by_role("textbox", name="••••••••").fill(password)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_load_state("domcontentloaded")


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.goto(BASE_URL)
        assert page.locator(".lp-slide").count() > 0
        assert page.locator('a[href^="/visitor/zoos/"]').count() > 0
        page.screenshot(path="tests/e2e/landing-desktop.png", full_page=True)

        login(page, "visitor", "visitor1@gmail.com", "Password123", "/visitor/")
        page.goto(f"{BASE_URL}/visitor/choose-zoo/Zoo%20Park")
        page.get_by_role("button", name="Select Zoo").first.click()
        page.goto(f"{BASE_URL}/visitor/bookings")
        page.locator("#new_service_id").select_option(
            page.locator("#new_service_id option").nth(1).get_attribute("value")
        )
        page.wait_for_timeout(500)
        assert page.locator("#cal-days-grid").count() == 1
        assert page.locator("#vb-payment-chips input").count() > 0
        page.get_by_role("button", name="6+").click()
        assert page.locator("#custom-guests-stepper").is_visible()
        page.screenshot(path="tests/e2e/visitor-bookings-desktop.png", full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
        page.screenshot(path="tests/e2e/visitor-bookings-mobile.png", full_page=True)

        login(page, "zootique_admin", "admin@zootique.com", "Password123", "/zootique-admin/")
        page.goto(f"{BASE_URL}/zootique-admin/subscriptions/subscription-plan")
        body = page.locator("body").inner_text()
        assert "Standard" in body and "Pro" in body
        assert "Basic" not in body and "Premium" not in body
        page.screenshot(path="tests/e2e/subscriptions-mobile.png", full_page=True)

        page.goto(f"{BASE_URL}/zootique-admin/email-log")
        email_log = page.locator("body").inner_text().lower()
        assert page.url.endswith("/zootique-admin/email-log")
        assert all(label in email_log for label in ("recipient", "subject", "body"))
        page.screenshot(path="tests/e2e/email-log-mobile.png", full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
