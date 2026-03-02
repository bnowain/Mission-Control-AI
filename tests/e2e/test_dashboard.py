"""
E2E Scenario 1 — Dashboard loads with health cards.

Asserts:
  - Page heading "Dashboard" is visible
  - At least one StatCard is rendered (checks for known label text)
  - Health status indicator (DB connected / ok / unknown) is visible
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_dashboard_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/")
    # h1 renders immediately (outside the loading block)
    page.wait_for_selector("h1:has-text('Dashboard')", timeout=10000)

    # Heading
    assert page.locator("h1").filter(has_text="Dashboard").is_visible(), \
        "Dashboard h1 not visible"

    # StatCards render after API calls complete — labels use CSS `text-transform: uppercase`
    # so innerText returns "HEALTH STATUS", not "Health Status"
    page.wait_for_function(
        "document.body.innerText.includes('HEALTH STATUS') || "
        "document.body.innerText.includes('ACTIVE TASKS')",
        timeout=20000,
    )

    body = page.inner_text("body")
    # CSS uppercase transform: StatCard labels appear in ALL CAPS in innerText
    known_labels = ["HEALTH STATUS", "ACTIVE TASKS", "SCHEMA VERSION", "WORKER STATUS"]
    found = [lbl for lbl in known_labels if lbl in body]
    assert found, f"No StatCard labels found. Checked: {known_labels}"

    # Health value and sublabel don't have uppercase CSS — check as-is
    health_indicators = ["ok", "DB connected", "DB disconnected", "unknown"]
    has_health = any(ind in body for ind in health_indicators)
    assert has_health, "No health indicator found on dashboard"
