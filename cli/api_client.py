"""
Mission Control CLI — API Client
==================================
Single httpx wrapper for all CLI → backend calls.
All state changes go through HTTP — no DB access from CLI.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from cli.config import CLIConfig

DEFAULT_TIMEOUT = 30.0
EXECUTE_TIMEOUT = 120.0


class MCClient:
    """Thin httpx wrapper for the Mission Control REST API."""

    def __init__(self, cfg: CLIConfig, debug: bool = False) -> None:
        self.base_url = cfg.api_endpoint.rstrip("/")
        self.debug = debug
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.api_key:
            self._headers["X-API-Key"] = cfg.api_key

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _handle_error(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("error") or str(body)
            except Exception:
                detail = resp.text or f"HTTP {resp.status_code}"
            from rich.console import Console
            Console(stderr=True).print(
                f"[red]Error {resp.status_code}:[/red] {detail}"
            )
            raise SystemExit(1)

    def get(self, path: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
        if self.debug:
            from rich.console import Console
            Console(stderr=True).print(f"[dim]GET {self._url(path)} params={params}[/dim]")
        with httpx.Client(headers=self._headers, timeout=timeout) as client:
            resp = client.get(self._url(path), params=params)
        self._handle_error(resp)
        return resp.json()

    def post(self, path: str, json: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
        if self.debug:
            from rich.console import Console
            Console(stderr=True).print(f"[dim]POST {self._url(path)} body={json}[/dim]")
        with httpx.Client(headers=self._headers, timeout=timeout) as client:
            resp = client.post(self._url(path), json=json or {})
        self._handle_error(resp)
        return resp.json()

    def delete(self, path: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
        if self.debug:
            from rich.console import Console
            Console(stderr=True).print(f"[dim]DELETE {self._url(path)}[/dim]")
        with httpx.Client(headers=self._headers, timeout=timeout) as client:
            resp = client.delete(self._url(path))
        self._handle_error(resp)
        # DELETE may return 204 No Content
        if resp.status_code == 204 or not resp.text:
            return {}
        return resp.json()

    def post_execute(self, path: str, json: Optional[dict] = None) -> Any:
        """POST with extended 120s timeout for task execution."""
        return self.post(path, json=json, timeout=EXECUTE_TIMEOUT)
