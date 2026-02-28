"""
Mission Control — Async DB Helpers
====================================
Thin wrapper to run synchronous SQLite operations on a thread pool,
keeping FastAPI's async event loop free.

Usage:
    from app.database.async_helpers import run_in_thread

    result = await run_in_thread(some_sync_db_function, arg1, arg2)

No new dependencies — uses asyncio.to_thread() (Python 3.9+).
"""

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_in_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Run a synchronous callable in the default thread pool executor.
    Returns the result when complete.

    Example:
        rows = await run_in_thread(get_tasks, project_id="01J...")
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
