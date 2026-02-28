"""
Mission Control CLI — Output Helpers
======================================
All output goes through these helpers.
If json_mode is True: print raw JSON.
If json_mode is False: use rich tables / panels.
"""

from __future__ import annotations

import json as _json
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

_console = Console()
_err_console = Console(stderr=True)

# Global flag — set by main.py callback via set_json_mode()
_json_mode: bool = False


def set_json_mode(enabled: bool) -> None:
    global _json_mode
    _json_mode = enabled


def is_json_mode() -> bool:
    return _json_mode


def print_json(data: Any) -> None:
    """Always print raw JSON regardless of mode (used when caller forces JSON)."""
    _console.print_json(_json.dumps(data, default=str))


def print_output(data: Any) -> None:
    """Print JSON if json_mode, else caller should use print_table/print_dict."""
    if _json_mode:
        print_json(data)


def print_table(title: str, columns: list[str], rows: list[list[Any]]) -> None:
    """Print a rich table, or JSON array if json_mode."""
    if _json_mode:
        records = [dict(zip(columns, row)) for row in rows]
        print_json(records)
        return
    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*[str(v) if v is not None else "" for v in row])
    _console.print(table)


def print_dict(title: str, data: dict) -> None:
    """Print a key/value panel, or JSON if json_mode."""
    if _json_mode:
        print_json(data)
        return
    lines = "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in data.items())
    _console.print(Panel(lines, title=title, expand=False))


def print_success(msg: str) -> None:
    if _json_mode:
        print_json({"status": "ok", "message": msg})
    else:
        _console.print(f"[green]✓[/green] {msg}")


def print_error(msg: str) -> None:
    _err_console.print(f"[red]✗[/red] {msg}")
