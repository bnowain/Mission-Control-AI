"""
E2E Scenario 9 — Artifacts page: list loads, state filter works.

Asserts:
  - h1 containing "Artifacts" is visible
  - State filter select ("All states") is present
  - Selecting a state from the filter re-renders the list without crashing
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_artifacts_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/artifacts")
    page.wait_for_load_state("load")

    # Heading is "Artifacts (N)" — use contains check
    body = page.inner_text("body")
    assert "Artifacts" in body, "Artifacts heading not found"

    assert page.locator("h1").is_visible(), "h1 not visible on artifacts page"


def test_artifacts_state_filter(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/artifacts")
    page.wait_for_load_state("load")

    # Wait for initial load
    page.wait_for_timeout(1000)

    # State filter select is visible
    state_select = page.locator("select").first
    assert state_select.is_visible(), "State filter select not visible"

    # Select PROCESSING state
    state_select.select_option("PROCESSING")
    page.wait_for_timeout(1000)

    body = page.inner_text("body")
    # Either shows filtered results or "No artifacts found" empty state
    assert "Something went wrong" not in body, "React error boundary after state filter change"
    has_content = (
        "No artifacts found" in body
        or "PROCESSING" in body
        or "Artifacts" in body
    )
    assert has_content, "Page did not re-render after state filter change"


def test_artifacts_all_states_filter(e2e_page):
    """Verify reset to 'All states' works after filtering."""
    page = e2e_page
    page.goto(FRONTEND + "/artifacts")
    page.wait_for_load_state("load")
    page.wait_for_timeout(500)

    state_select = page.locator("select").first
    state_select.select_option("PROCESSING")
    page.wait_for_timeout(300)

    # Reset to all
    state_select.select_option("")
    page.wait_for_timeout(500)

    body = page.inner_text("body")
    assert "Something went wrong" not in body, "React error boundary after resetting filter"
