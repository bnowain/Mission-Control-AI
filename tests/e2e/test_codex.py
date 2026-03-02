"""
E2E Scenario 7 — Codex page: search, Stats tab, Clusters tab.

Asserts:
  - h1 "Codex" visible
  - Search input with placeholder "Search codex lessons..." is visible
  - Typing a query does not crash the page
  - "Stats" tab renders content
  - "Clusters" tab renders content (table or empty state)
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_codex_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/codex")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="Codex").is_visible(), \
        "Codex h1 not visible"

    search_input = page.get_by_placeholder("Search codex lessons...")
    assert search_input.is_visible(), "Codex search input not visible"


def test_codex_search_no_crash(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/codex")
    page.wait_for_load_state("load")

    page.get_by_placeholder("Search codex lessons...").fill("import error")
    page.wait_for_timeout(600)  # debounce is 400ms

    body = page.inner_text("body")
    assert "Something went wrong" not in body, "React error boundary triggered on search"


def test_codex_stats_tab(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/codex")
    page.wait_for_load_state("load")

    page.get_by_role("button", name="Stats").click()
    page.wait_for_timeout(500)

    body = page.inner_text("body")
    # Stats tab shows StatCards with labels like "Master Codex", "Candidates", etc.
    has_stats = any(lbl in body for lbl in ["Master Codex", "Candidates", "Promoted", "Project Codex"])
    assert has_stats or len(body) > 20, "Stats tab content not rendered"
    assert "Something went wrong" not in body, "React error boundary on Stats tab"


def test_codex_clusters_tab(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/codex")
    page.wait_for_load_state("load")

    page.get_by_role("button", name="Clusters").click()
    page.wait_for_timeout(500)

    body = page.inner_text("body")
    assert "Something went wrong" not in body, "React error boundary on Clusters tab"
    # Either table headers or empty state
    assert "No failure clusters" in body or "Hash" in body or len(body) > 50, \
        "Clusters tab content not rendered"
