"""
Shared fixtures for Playwright E2E tests.

Requirements:
  pip install pytest-playwright
  playwright install chromium

Run all E2E tests:
  python -m pytest tests/e2e/ -v -m e2e

Auto-skip behaviour:
  - If pytest-playwright is not installed → all tests skip with install hint
  - If backend (:8860) or frontend (:5174) unreachable → all tests skip
"""
import pytest
import httpx

FRONTEND = "http://localhost:5174"
BACKEND = "http://localhost:8860"

# Detect whether pytest-playwright is installed.
# When it is NOT installed, provide a stub `page` fixture so tests skip cleanly
# instead of erroring with "fixture 'page' not found".
try:
    import pytest_playwright  # noqa: F401
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

    @pytest.fixture  # type: ignore[misc]
    def page():  # type: ignore[misc]
        pytest.skip(
            "pytest-playwright not installed — "
            "run: pip install pytest-playwright && playwright install chromium"
        )


@pytest.fixture(scope="session")
def _check_servers():
    """Skip all E2E tests if backend or frontend is unreachable.

    Session-scoped: checked once per pytest session.
    """
    for url, name in [
        (BACKEND + "/api/health", "backend"),
        (FRONTEND, "frontend"),
    ]:
        try:
            httpx.get(url, timeout=3)
        except Exception:
            pytest.skip(f"E2E skipped: {name} not running at {url}")


@pytest.fixture
def e2e_page(page, _check_servers):
    """Playwright page with console error capture.

    Use this fixture in all E2E tests instead of the bare `page` fixture.
    Console errors are collected but not auto-asserted (soft check).
    """
    errors: list[str] = []
    page.on(
        "console",
        lambda m: errors.append(m.text) if m.type == "error" else None,
    )
    page.set_default_timeout(15000)
    yield page


def wait_for_url(page, fragment: str, timeout_ms: int = 15000) -> None:
    """SPA-safe URL assertion using window.location.href.

    React Router uses pushState which does not trigger Playwright's
    page.wait_for_url(). This function uses wait_for_function which
    correctly detects pushState navigation.
    """
    page.wait_for_function(
        f"window.location.href.includes('{fragment}')",
        timeout=timeout_ms,
    )
