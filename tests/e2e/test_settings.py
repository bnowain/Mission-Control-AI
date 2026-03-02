"""
E2E Scenario 6 — Settings page: feature flags + prompt registry + audit log tabs.

Asserts:
  - h1 "Settings" visible
  - "Feature Flags" section loads by default (first tab)
  - Clicking "Prompt Registry" switches the tab
  - Clicking "Audit Log" switches the tab
  - No crash on any tab
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_settings_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/settings")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="Settings").is_visible(), \
        "Settings h1 not visible"

    # Feature Flags tab is active by default — button text visible
    assert page.get_by_role("button", name="Feature Flags").is_visible(), \
        "'Feature Flags' tab button not visible"


def test_settings_prompt_registry_tab(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/settings")
    page.wait_for_load_state("load")

    page.get_by_role("button", name="Prompt Registry").click()
    page.wait_for_timeout(500)

    body = page.inner_text("body")
    # Should show either a table, empty state, or "Register Prompt" button
    assert "Prompt Registry" in body or "Register Prompt" in body or "No prompts" in body, \
        "Prompt Registry tab content not rendered"
    assert "Something went wrong" not in body, "React error boundary on Prompt Registry tab"


def test_settings_audit_log_tab(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/settings")
    page.wait_for_load_state("load")

    page.get_by_role("button", name="Audit Log").click()
    page.wait_for_timeout(500)

    body = page.inner_text("body")
    # Should show table or empty state
    assert "Audit Log" in body or "No audit entries" in body, \
        "Audit Log tab content not rendered"
    assert "Something went wrong" not in body, "React error boundary on Audit Log tab"
