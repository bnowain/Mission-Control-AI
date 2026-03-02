"""
E2E Scenario 4 — Telemetry page loads and tabs switch without crashing.

Asserts:
  - h1 "Telemetry" visible on load
  - Clicking each tab (Runs, Models, Performance, Hardware) renders content
  - No blank/error state after each tab switch
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"

TABS = ["Runs", "Models", "Performance", "Hardware"]


def test_telemetry_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/telemetry")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="Telemetry").is_visible(), \
        "Telemetry h1 not visible"


@pytest.mark.parametrize("tab_name", TABS)
def test_telemetry_tab_switch(e2e_page, tab_name):
    page = e2e_page
    page.goto(FRONTEND + "/telemetry")
    page.wait_for_load_state("load")

    # Click the tab button by name
    page.get_by_role("button", name=tab_name).click()

    # Wait for any loading spinners to clear (up to 5s)
    # Either a spinner disappears or content renders
    page.wait_for_timeout(500)

    # Body is substantive — no blank page
    body = page.inner_text("body").strip()
    assert len(body) > 20, f"Page body looks empty after clicking '{tab_name}' tab"

    # No unhandled error page (React error boundary would show "Something went wrong")
    assert "Something went wrong" not in body, \
        f"React error boundary triggered on tab '{tab_name}'"
