"""
E2E Scenario 3 — Create task via the Tasks UI form.

Steps:
  1. Navigate to /tasks, wait for the page to be interactive
  2. Click "New Task" button
  3. Fill "Project ID" input with "e2e-test"
  4. Click "Create"
  5. Assert SPA navigates to /tasks/<id>  OR  capture an API error
  6. Assert the task detail page loaded (project_id visible)

Refactored from tests/test_e2e_task_execution.py (standalone script).
Does NOT execute the task or stream SSE — that is covered by the standalone script.
"""
import pytest

pytestmark = pytest.mark.e2e

FRONTEND = "http://localhost:5174"


def test_create_task(e2e_page):
    page = e2e_page

    # Step 1: Navigate to /tasks — wait for h1 (reliable page-ready signal)
    page.goto(FRONTEND + "/tasks")
    page.wait_for_selector("h1:has-text('Tasks')", timeout=10000)

    # Step 2: Open task creation form
    new_task_btn = page.get_by_role("button", name="New Task")
    new_task_btn.wait_for(state="visible", timeout=5000)
    new_task_btn.click()

    # Step 3: Fill project ID (controlled input with placeholder "Project ID")
    project_input = page.get_by_placeholder("Project ID")
    project_input.wait_for(state="visible", timeout=5000)
    project_input.fill("e2e-test")

    # Step 4: Submit
    create_btn = page.get_by_role("button", name="Create")
    create_btn.wait_for(state="visible", timeout=5000)
    create_btn.click()

    # Step 5: Wait for EITHER:
    #   a) Successful navigation to /tasks/<id>
    #   b) An API error shown on the Tasks page (creation failed)
    page.wait_for_function(
        "window.location.href.includes('/tasks/') || "
        "document.body.innerText.includes('API error') || "
        "document.body.innerText.includes('error')",
        timeout=30000,
    )

    current_url = page.url
    if "/tasks/" not in current_url:
        body = page.inner_text("body")
        # Extract error context for debugging
        err_snippet = body[body.lower().find("error"):body.lower().find("error") + 200] \
            if "error" in body.lower() else "(no error text found)"
        pytest.fail(
            f"Task creation did not navigate away from /tasks.\n"
            f"URL: {current_url}\n"
            f"Error context: {err_snippet}"
        )

    task_id = current_url.split("/")[-1]
    assert task_id, "Could not extract task ID from URL"

    # Step 6: Wait for task data to load (page shows "Loading task..." while fetching)
    page.wait_for_function(
        "!document.body.innerText.includes('Loading task')",
        timeout=10000,
    )

    body = page.inner_text("body")
    # TaskDetailPage renders project_id as plain text (no CSS uppercase)
    assert "e2e-test" in body, \
        f"Project 'e2e-test' not visible in task detail page (task {task_id})"
