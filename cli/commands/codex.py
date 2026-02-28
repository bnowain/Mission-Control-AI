"""
CLI command group: mission-control codex
=========================================
codex search  → GET  /api/codex/search?q=
codex stats   → GET  /codex/stats
codex query   → POST /codex/query
codex promote → POST /codex/promote
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(help="Search, query, and manage the Codex knowledge base.")


@app.command("search")
def codex_search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query text"),
    limit: int = typer.Option(10, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """Full-text search the Codex (Atlas-exposed endpoint)."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    result = client.get("/api/codex/search", params={"q": query, "limit": limit, "offset": offset})
    entries = result if isinstance(result, list) else result.get("results", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            e.get("id", ""),
            (e.get("pattern_summary") or "")[:60],
            e.get("task_type", ""),
            e.get("model_source", ""),
            e.get("codex_promoted", ""),
        ]
        for e in entries
    ]
    print_table("Codex Search Results", ["ID", "Pattern Summary", "Task Type", "Model Source", "Promoted"], rows)


@app.command("stats")
def codex_stats(ctx: typer.Context) -> None:
    """Show Codex stats (total entries, promoted count, etc.)."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get("/codex/stats")
    if is_json_mode():
        print_json(result)
        return
    print_dict("Codex Stats", result)


@app.command("query")
def codex_query(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Natural language query for Codex"),
    project: Optional[str] = typer.Option(None, "--project", help="Filter by project ID"),
) -> None:
    """Query the Codex with a natural language prompt."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    body: dict = {"query": text}
    if project:
        body["project_id"] = project

    result = client.post("/codex/query", json=body)
    entries = result if isinstance(result, list) else result.get("results", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            e.get("id", ""),
            (e.get("pattern_summary") or "")[:60],
            e.get("task_type", ""),
            e.get("model_source", ""),
            e.get("codex_promoted", ""),
        ]
        for e in entries
    ]
    print_table("Codex Query Results", ["ID", "Pattern Summary", "Task Type", "Model Source", "Promoted"], rows)


@app.command("promote")
def codex_promote(
    ctx: typer.Context,
    entry_id: str = typer.Argument(..., help="Codex entry UUID to promote"),
    by: str = typer.Option("human", "--by", help="Source promoting this entry (human/claude/local_worker)"),
) -> None:
    """Promote a Codex candidate entry to the active knowledge base."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_success

    body = {"entry_id": entry_id, "promoted_by": by}
    result = client.post("/codex/promote", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_success(f"Codex entry {entry_id} promoted by {by}.")
