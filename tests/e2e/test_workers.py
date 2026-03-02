"""
E2E Scenario 10 — Workers page: stats, pipelines, jobs table.

Asserts:
  - h1 "Workers" visible
  - Stats section renders (Queued/Running/Completed/Failed/Retrying/Total cards)
    or shows "No worker stats" if empty
  - Jobs section renders (table or empty state)
  - No crash on page load
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_workers_page_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/workers")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="Workers").is_visible(), \
        "Workers h1 not visible"


def test_workers_stats_render(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/workers")
    page.wait_for_load_state("load")

    # Wait for loading to complete.
    # StatCard labels use CSS text-transform:uppercase → innerText returns "QUEUED" not "Queued"
    page.wait_for_function(
        "document.body.innerText.includes('QUEUED') || "
        "document.body.innerText.includes('RUNNING') || "
        "document.body.innerText.includes('No jobs found')",
        timeout=15000,
    )

    body = page.inner_text("body")
    assert "Something went wrong" not in body, "React error boundary on workers page"

    # StatCard labels are uppercase in innerText due to CSS text-transform
    stat_labels = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "RETRYING", "TOTAL"]
    has_stats = any(lbl in body for lbl in stat_labels)
    assert has_stats, "Workers stats section not rendered"


def test_workers_jobs_section(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/workers")
    page.wait_for_load_state("load")

    # Wait for all three API calls to complete (stats + pipelines + jobs).
    # The "Jobs (N)" heading has CSS uppercase → appears as "JOBS (" in innerText
    page.wait_for_function(
        "document.body.innerText.includes('JOBS (') || "
        "document.body.innerText.includes('No jobs found')",
        timeout=15000,
    )

    body = page.inner_text("body")
    # "Jobs" heading (uppercase CSS) and column headers
    has_jobs_section = "JOBS" in body or "No jobs found" in body
    assert has_jobs_section, "Jobs section not found on workers page"

    # Either jobs listed (column headers or status badges) or empty state
    has_content = (
        "No jobs found" in body
        or "JOB ID" in body   # DataTable column header has uppercase CSS
        or "QUEUED" in body
        or "COMPLETED" in body
        or "JOBS (0)" in body
    )
    assert has_content, "Jobs table or empty state not rendered"
    assert "Something went wrong" not in body, "React error boundary on jobs section"
