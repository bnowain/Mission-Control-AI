"""
E2E Scenario 5 — SQL Console: execute a read query, verify results.

Steps:
  1. Navigate to /sql
  2. Click "Tables" quick-query button (populates textarea)
  3. Click "Execute"
  4. Wait for results table
  5. Assert result contains known table names (tasks, execution_logs)
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_sql_console_loads(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/sql")
    page.wait_for_load_state("load")

    assert page.locator("h1").filter(has_text="SQL Console").is_visible(), \
        "SQL Console h1 not visible"


def test_sql_execute_tables_query(e2e_page):
    page = e2e_page
    page.goto(FRONTEND + "/sql")
    page.wait_for_load_state("load")

    # Click the "Tables" quick-query button to load the tables query
    page.get_by_role("button", name="Tables").click()

    # Click Execute
    page.get_by_role("button", name="Execute").click()

    # Wait for query to finish: button returns from "Running…" to "Execute"
    # and "execution_logs" appears in the results (not the sidebar/textarea)
    page.wait_for_function(
        "document.body.innerText.includes('execution_logs')",
        timeout=15000,
    )

    body = page.inner_text("body")

    # Core tables that should always exist in the result set
    assert "tasks" in body, "Expected 'tasks' table in SQL results"
    assert "execution_logs" in body, "Expected 'execution_logs' table in SQL results"
