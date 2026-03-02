"""
E2E Scenario 8 — Router Analytics: stats table, Test Router button.

Asserts:
  - h1 "Router Analytics" visible
  - Stats section renders (table or "No router stats yet" empty state)
  - "Test Router" button is visible and clickable
  - Clicking Test Router produces a routing decision or error (no crash)
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_router_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/router")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="Router Analytics").is_visible(), \
        "Router Analytics h1 not visible"


def test_router_stats_section(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/router")
    page.wait_for_load_state("load")

    # Wait for async data load.
    # "Model Performance" heading has CSS uppercase → "MODEL PERFORMANCE" in innerText.
    # Empty state "No router stats yet" has no uppercase CSS → appears as-is.
    page.wait_for_function(
        "document.body.innerText.includes('MODEL PERFORMANCE') || "
        "document.body.innerText.includes('No router stats yet')",
        timeout=10000,
    )

    body = page.inner_text("body")
    has_content = (
        "No router stats yet" in body
        or "MODEL PERFORMANCE" in body
    )
    assert has_content, "Router stats section not rendered"
    assert "Something went wrong" not in body, "React error boundary on router page"


def test_router_test_button(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/router")
    page.wait_for_load_state("load")

    # "Test Router" button is in the Test Router section
    test_btn = page.get_by_role("button", name="Test Router")
    assert test_btn.is_visible(), "'Test Router' button not visible"

    test_btn.click()

    # Brief pause to let React process the click and flip testing=true
    # (avoids race condition where wait_for_function fires before re-render)
    page.wait_for_timeout(300)

    # Wait for API call to complete.
    # Success: the result section heading has CSS text-transform:uppercase →
    #   "Routing Decision" appears as "ROUTING DECISION" in innerText.
    # Failure: ErrorBanner shows "API error 500: ..." or similar.
    page.wait_for_function(
        "document.body.innerText.includes('ROUTING DECISION') || "
        "document.body.innerText.includes('API error') || "
        "document.body.innerText.includes('Error') || "
        "document.body.innerText.includes('error')",
        timeout=25000,
    )

    body = page.inner_text("body")
    # Routing Decision section OR an error banner appeared
    has_result = (
        "ROUTING DECISION" in body
        or "API error" in body
        or "Error" in body
        or "error" in body
    )
    assert has_result, "Test Router button click produced no visible result"
    assert "Something went wrong" not in body, "React error boundary after Test Router click"
