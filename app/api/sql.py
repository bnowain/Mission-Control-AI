"""
Mission Control — SQL Query API
=================================
POST /sql/query → read-only by default; write_mode=True opt-in.

Safety layers (defense-in-depth):
  1. PRAGMA query_only=ON for read-only queries
  2. Keyword blocklist to catch destructive statements
"""

from fastapi import APIRouter, HTTPException

from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.schemas import SqlQueryRequest, SqlQueryResponse

router = APIRouter(prefix="/sql", tags=["sql"])

# Statements that are never allowed through the SQL API
_BLOCKED_KEYWORDS = {
    "drop",
    "truncate",
    "alter",
    "attach",
    "detach",
    "vacuum",
    "pragma",
}


def _check_blocked(sql: str) -> None:
    first_word = sql.strip().split()[0].lower() if sql.strip() else ""
    if first_word in _BLOCKED_KEYWORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Statement type '{first_word.upper()}' is not permitted via the SQL API.",
        )


def _run_query_sync(sql: str, params: list, write_mode: bool) -> SqlQueryResponse:
    conn = get_connection()
    try:
        if not write_mode:
            conn.execute("PRAGMA query_only=ON;")

        cur = conn.execute(sql, params)

        if cur.description is None:
            # DML statement (INSERT/UPDATE/DELETE) in write_mode
            conn.commit()
            return SqlQueryResponse(columns=[], rows=[], row_count=cur.rowcount)

        columns = [d[0] for d in cur.description]
        rows = [list(row) for row in cur.fetchall()]
        return SqlQueryResponse(columns=columns, rows=rows, row_count=len(rows))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/query", response_model=SqlQueryResponse)
async def sql_query(req: SqlQueryRequest) -> SqlQueryResponse:
    """
    Execute a SQL query against the Mission Control database.

    - Read-only by default (PRAGMA query_only=ON + keyword blocklist).
    - Set write_mode=true for INSERT/UPDATE/DELETE.
    - DROP, TRUNCATE, ALTER, ATTACH, DETACH, VACUUM, PRAGMA are always blocked.
    """
    _check_blocked(req.sql)
    return await run_in_thread(_run_query_sync, req.sql, req.params, req.write_mode)
