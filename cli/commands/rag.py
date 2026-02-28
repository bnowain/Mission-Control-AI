"""
CLI command group: mission-control rag
=======================================
rag index  → POST /rag/index
rag search → GET  /rag/search
rag stats  → GET  /rag/stats
"""

from __future__ import annotations

from typing import List, Optional

import typer

app = typer.Typer(help="RAG: index codebases/web pages and search embeddings.")


@app.command("index")
def rag_index(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path", help="Directory to index"),
    project: str = typer.Option(..., "--project", help="Project ID to scope this index"),
    extensions: Optional[List[str]] = typer.Option(
        None, "--extension", help="File extensions to include (e.g. .py). Repeat for multiple."
    ),
    max_kb: int = typer.Option(100, "--max-kb", help="Skip files larger than this (KB)"),
) -> None:
    """Index a local codebase directory for semantic search."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    body: dict = {
        "project_id": project,
        "path": path,
        "max_file_kb": max_kb,
    }
    if extensions:
        body["extensions"] = extensions

    result = client.post("/rag/index", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        "Codebase Indexed",
        {
            "project_id": result.get("project_id"),
            "path": result.get("path"),
            "indexed_files": result.get("indexed_files"),
            "total_chunks": result.get("total_chunks"),
            "skipped_files": result.get("skipped_files"),
        },
    )
    errors = result.get("errors", [])
    if errors:
        from cli.output import print_error
        print_error(f"{len(errors)} file(s) had errors — use --json to see details")


@app.command("search")
def rag_search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query text"),
    project: Optional[str] = typer.Option(None, "--project", help="Filter by project ID"),
    source_type: Optional[str] = typer.Option(
        None, "--type", help="Filter: artifact|codebase|web_page|codex"
    ),
    limit: int = typer.Option(10, "--limit", help="Max results"),
) -> None:
    """Semantic search over embeddings."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table, print_success

    params: dict = {"q": query, "limit": limit}
    if project:
        params["project_id"] = project
    if source_type:
        params["source_type"] = source_type

    result = client.get("/rag/search", params=params)
    hits = result.get("results", [])

    if is_json_mode():
        print_json(result)
        return

    if not hits:
        print_success("No results found.")
        return

    rows = [
        [
            h.get("source_type", ""),
            (h.get("source_id", ""))[:40],
            h.get("chunk_index", ""),
            f"{h.get('score', 0):.3f}",
            (h.get("chunk_text", ""))[:80].replace("\n", " "),
        ]
        for h in hits
    ]
    print_table(
        f"RAG Search — '{query}' ({len(hits)} results)",
        ["Type", "Source ID", "Chunk", "Score", "Text (preview)"],
        rows,
    )


@app.command("stats")
def rag_stats(ctx: typer.Context) -> None:
    """Show embedding counts by source type."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_table

    result = client.get("/rag/stats")
    if is_json_mode():
        print_json(result)
        return

    by_type = result.get("by_source_type", [])
    if by_type:
        rows = [
            [r.get("source_type", ""), r.get("chunk_count", 0), r.get("source_count", 0)]
            for r in by_type
        ]
        print_table(
            f"RAG Embeddings (total: {result.get('total_chunks', 0)} chunks)",
            ["Source Type", "Chunks", "Sources"],
            rows,
        )
    else:
        print_dict("RAG Stats", {"total_chunks": 0, "message": "No embeddings yet."})


@app.command("delete-index")
def rag_delete_index(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="Project ID whose codebase index to remove"),
) -> None:
    """Remove the codebase index for a project."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_success

    result = client.delete(f"/rag/index/{project}")
    if is_json_mode():
        print_json(result)
        return
    print_success(
        f"Codebase index for project '{project}' removed ({result.get('rows_deleted', 0)} rows)"
    )
