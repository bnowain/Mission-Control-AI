"""
Mission Control — Web Fetcher
================================
Fetches a URL and extracts clean plain text.
Uses httpx for the HTTP request and html2text for HTML → text conversion.

Falls back gracefully if html2text is not installed.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.core.logging import get_logger

log = get_logger("rag.web_fetcher")

_FETCH_TIMEOUT = 30.0
_MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB limit

try:
    import html2text as _html2text_mod
    _HTML2TEXT_AVAILABLE = True
except ImportError:
    _HTML2TEXT_AVAILABLE = False


def fetch_url(url: str) -> Optional[str]:
    """
    Fetch a URL and return clean plain text.
    Returns None on any fetch or parse error.

    The returned text is suitable for chunking and embedding.
    """
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "MissionControl-RAG/0.1"},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning("Web fetch HTTP error", url=url, status=exc.response.status_code)
        return None
    except httpx.ConnectError:
        log.warning("Web fetch connection error", url=url)
        return None
    except Exception as exc:
        log.warning("Web fetch failed", url=url, exc=str(exc))
        return None

    # Guard against huge pages
    content_bytes = resp.content
    if len(content_bytes) > _MAX_CONTENT_BYTES:
        content_bytes = content_bytes[:_MAX_CONTENT_BYTES]

    content_type = resp.headers.get("content-type", "")

    # Plain text — return as-is
    if "text/plain" in content_type:
        try:
            return content_bytes.decode("utf-8", errors="replace").strip()
        except Exception:
            return None

    # HTML — convert to markdown-like text
    raw_html = content_bytes.decode("utf-8", errors="replace")
    return _html_to_text(raw_html, url)


def _html_to_text(html: str, url: str = "") -> Optional[str]:
    """Convert HTML to clean plain text."""
    if _HTML2TEXT_AVAILABLE:
        try:
            h = _html2text_mod.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            h.ignore_emphasis = False
            h.body_width = 0          # no line wrapping
            text = h.handle(html).strip()
            return text if text else None
        except Exception as exc:
            log.warning("html2text conversion failed", url=url, exc=str(exc))
            # Fall through to basic strip

    # Minimal fallback: strip tags with regex
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None
