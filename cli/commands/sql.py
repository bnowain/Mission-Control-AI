"""
CLI command group: mission-control sql
=======================================
sql <query>             → POST /sql/query (read-only)
sql <query> --write     → POST /sql/query (write mode)
sql --interactive       → REPL loop
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(help="Execute SQL queries against the Mission Control database.")


@app.callback(invoke_without_command=True)
def sql_cmd(
    ctx: typer.Context,
    query: Optional[str] = typer.Argument(None, help="SQL query to execute"),
    write: bool = typer.Option(False, "--write", help="Allow write operations (INSERT/UPDATE/DELETE)"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Enter interactive SQL REPL"),
) -> None:
    """Execute a SQL query or start an interactive REPL."""
    client = ctx.obj["client"]

    if interactive:
        _run_sql_repl(client)
        return

    if query is None:
        typer.echo("Provide a query or use --interactive.")
        raise typer.Exit(1)

    _run_query(client, query, write)


def _run_query(client, query: str, write: bool = False) -> None:
    from cli.output import is_json_mode, print_json, print_table, print_dict

    body: dict = {"sql": query}
    if write:
        body["write_mode"] = True

    result = client.post("/sql/query", json=body)

    if is_json_mode():
        print_json(result)
        return

    rows_data = result.get("rows") or []
    columns = result.get("columns") or []

    if columns and rows_data:
        print_table(
            f"Query Results ({len(rows_data)} row{'s' if len(rows_data) != 1 else ''})",
            columns,
            rows_data,
        )
    else:
        # Write result or empty SELECT
        print_dict(
            "Query Result",
            {
                "rows_affected": result.get("rows_affected", 0),
                "message": result.get("message", "OK"),
            },
        )


def _run_sql_repl(client) -> None:
    """Interactive SQL REPL. Type .quit to exit."""
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()
    console.print("[bold cyan]Mission Control — Interactive SQL[/bold cyan]")
    console.print("Type a SQL query and press Enter. Type [bold].quit[/bold] to exit.")
    console.print()

    while True:
        try:
            query = Prompt.ask("[bold blue]sql>[/bold blue]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting SQL REPL.[/dim]")
            break

        if not query:
            continue
        if query.lower() in (".quit", ".exit", "\\q", "exit", "quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        write_mode = query.strip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")
        )
        try:
            _run_query(client, query, write=write_mode)
        except SystemExit:
            # _run_query calls sys.exit on HTTP errors — catch so REPL continues
            pass
