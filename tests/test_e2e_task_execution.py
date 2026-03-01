"""
E2E test: Task creation + SSE streaming execution end-to-end.
Run with: python tests/test_e2e_task_execution.py

Requires:
  - Backend running on 8861 (or whatever .backend-port says)
  - Vite dev server on 5174
  - playwright installed: pip install playwright && playwright install chromium
"""
import re
import sys
import time

FRONTEND = "http://localhost:5174"
BACKEND = "http://localhost:8861"


def _wait_for_url_contains(page, fragment: str, timeout_ms: int = 15000) -> bool:
    """Wait until window.location.href contains `fragment`.
    Uses page.wait_for_function which correctly tracks SPA pushState navigation.
    """
    try:
        page.wait_for_function(
            f"window.location.href.includes('{fragment}')",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def run_e2e():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        # ── Step 1: Navigate to /tasks ────────────────────────────────────────
        page.goto(FRONTEND + "/tasks")
        page.wait_for_load_state("load", timeout=10000)
        assert "Mission Control" in page.title(), f"Wrong title: {page.title()}"
        print("[1] Navigated to /tasks OK")

        # ── Step 2: Create a task ─────────────────────────────────────────────
        page.get_by_role("button", name="New Task").click()
        time.sleep(0.5)

        project_input = page.get_by_placeholder("Project ID")
        project_input.wait_for(state="visible", timeout=3000)
        project_input.fill("e2e-test")

        page.get_by_role("button", name="Create").click()

        if not _wait_for_url_contains(page, "/tasks/", timeout_ms=15000):
            # Dump page state for debugging
            print("ERROR: Did not navigate to task detail")
            print("URL:", page.url)
            print("Page text:", page.inner_text("body")[:500])
            sys.exit(1)

        task_id = page.url.split("/")[-1]
        print(f"[2] Task created: {task_id}")
        time.sleep(0.3)

        # ── Step 3: Fill the prompt ───────────────────────────────────────────
        textarea = page.locator('textarea[placeholder*="Enter prompt"]')
        textarea.wait_for(state="visible", timeout=5000)
        textarea.fill('Output the single word: hello')
        print("[3] Prompt filled")

        # ── Step 4: Click Execute ─────────────────────────────────────────────
        page.get_by_role("button", name="Execute").click()
        print("[4] Execute clicked — waiting for result (up to 120s)...")

        # ── Step 5: Wait for Score to appear ─────────────────────────────────
        try:
            page.wait_for_selector("text=Score", timeout=120_000)
        except Exception:
            print("TIMEOUT waiting for Score")
            print("Page:", page.inner_text("body")[:800])
            sys.exit(1)

        print("[5] Score element appeared")

        # ── Step 6: Validate result ───────────────────────────────────────────
        body = page.inner_text("body")

        score_m = re.search(r"Score\s+([\d.]+)/100", body)
        assert score_m, f"Score not found in page body"
        score = float(score_m.group(1))
        print(f"[6] Score: {score}/100")

        # Verify SSE events appeared
        assert "Loop 1" in body, "Expected 'Loop 1' event in timeline"
        print("[6] Loop 1 event present in timeline")

        # Verify status badge
        has_status = any(s in body for s in ("passed", "failed", "completed", "Completed", "Failed"))
        assert has_status, "Expected a status badge"
        print(f"[6] Status badge present")

        # No console errors
        if console_errors:
            print(f"[!] Console errors: {console_errors[:5]}")

        browser.close()
        print("\n=== E2E TEST PASSED ===")
        print(f"    Task ID: {task_id}")
        print(f"    Score:   {score}/100")


if __name__ == "__main__":
    run_e2e()
