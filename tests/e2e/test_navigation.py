"""
E2E Scenario 2 — Sidebar navigation reaches all major pages.

Clicks each sidebar NavLink and asserts the target page heading is visible.
Validates no page crashes during navigation (no error page, no blank body).
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"

# (sidebar_link_label, expected_h1_text, url_fragment)
NAV_CASES = [
    ("Tasks",       "Tasks",            "/tasks"),
    ("Plans",       "Plans",            "/plans"),
    ("Codex",       "Codex",            "/codex"),
    ("Router",      "Router Analytics", "/router"),
    ("Telemetry",   "Telemetry",        "/telemetry"),
    ("SQL Console", "SQL Console",      "/sql"),
    ("Workers",     "Workers",          "/workers"),
    ("Artifacts",   "Artifacts",        "/artifacts"),
    ("Settings",    "Settings",         "/settings"),
]


@pytest.mark.parametrize("link_label,heading,fragment", NAV_CASES)
def test_sidebar_navigation(e2e_page, link_label, heading, fragment):
    page = e2e_page
    page.goto(FRONTEND + "/")
    page.wait_for_load_state("load")

    # Click the sidebar link by its text
    page.get_by_role("link", name=link_label).first.click()

    # Wait for the target page's h1 to appear — this covers both:
    # 1. The SPA URL change (pushState)
    # 2. React mounting the new route component and rendering its h1
    # Using wait_for_selector is more robust than URL check + is_visible()
    # because React renders asynchronously after the URL changes.
    page.wait_for_selector(f"h1:has-text('{heading}')", timeout=10000)

    # Heading is visible
    assert page.locator("h1").filter(has_text=heading).is_visible(), \
        f"Expected h1 '{heading}' after clicking '{link_label}'"

    # Body is not empty (no blank crash)
    body = page.inner_text("body").strip()
    assert len(body) > 20, f"Page body looks empty after navigating to {fragment}"
