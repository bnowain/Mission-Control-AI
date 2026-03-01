"""
Mission Control — Routing Performance Report Generator
=======================================================
Queries execution_logs (with JOIN to tasks) to produce a structured
performance report comparing model success rates by task type.

The report is read-only and fail-safe: any DB error returns an empty
report structure so callers always get a valid dict.

Usage:
    from app.router.report import generate_routing_report
    report = generate_routing_report(window_days=30)
"""

from __future__ import annotations

import datetime
from typing import Any

from app.core.feature_flags import is_feature_enabled
from app.core.logging import get_logger
from app.router.adaptive import _ADAPTIVE_IMPROVEMENT_THRESHOLD, _TASK_ROUTING

log = get_logger("router.report")

# Minimum executions in a model+task-type cell to emit a recommendation
_REC_MIN_SAMPLES = 10


def generate_routing_report(window_days: int = 30) -> dict[str, Any]:
    """
    Generate a routing performance report for the last ``window_days`` days.

    Always returns a valid dict — any internal error is caught and logged,
    and an empty-report skeleton is returned instead of raising.
    """
    window_days = max(1, int(window_days))
    try:
        return _build_report(window_days)
    except Exception as exc:
        log.warning("Report generation failed", exc=str(exc))
        return _empty_report(window_days)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _empty_report(window_days: int) -> dict[str, Any]:
    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "window_days": window_days,
        "total_executions": 0,
        "adaptive_router_enabled": False,
        "summary": {
            "overall_success_rate": 0.0,
            "overall_avg_score": 0.0,
            "models_active": 0,
            "task_types_seen": 0,
        },
        "per_model": [],
        "per_task_type": [],
        "recommendations": [],
    }


def _build_report(window_days: int) -> dict[str, Any]:
    from app.database.init import get_connection

    window_expr = f"datetime('now', '-{window_days} days')"

    conn = get_connection()
    try:
        # ── Overall stats ─────────────────────────────────────────────────
        overall_row = conn.execute(
            f"""
            SELECT COUNT(*)                                        AS total,
                   AVG(score)                                      AS avg_score,
                   AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END)    AS success_rate
            FROM execution_logs
            WHERE created_at >= {window_expr}
            """
        ).fetchone()

        total           = int(overall_row["total"] or 0)
        overall_sr      = float(overall_row["success_rate"] or 0.0)
        overall_avg_sc  = float(overall_row["avg_score"] or 0.0)

        # ── Per-model stats ───────────────────────────────────────────────
        model_rows = conn.execute(
            f"""
            SELECT e.model_id,
                   COUNT(*)                                        AS executions,
                   AVG(CASE WHEN e.passed THEN 1.0 ELSE 0.0 END)  AS success_rate,
                   AVG(e.score)                                    AS avg_score,
                   AVG(e.duration_ms)                             AS avg_duration_ms,
                   AVG(e.retries)                                  AS avg_retries
            FROM execution_logs e
            WHERE e.created_at >= {window_expr}
            GROUP BY e.model_id
            ORDER BY executions DESC
            """
        ).fetchall()

        # ── Per-task-type, per-model cross breakdown ───────────────────────
        cross_rows = conn.execute(
            f"""
            SELECT t.task_type,
                   e.model_id,
                   COUNT(*)                                        AS n,
                   AVG(CASE WHEN e.passed THEN 1.0 ELSE 0.0 END)  AS success_rate
            FROM execution_logs e
            JOIN tasks t ON e.task_id = t.id
            WHERE e.created_at >= {window_expr}
            GROUP BY t.task_type, e.model_id
            ORDER BY t.task_type, n DESC
            """
        ).fetchall()

        # ── Per-model task-type breakdown (for task_types dict) ────────────
        model_task_rows = conn.execute(
            f"""
            SELECT e.model_id,
                   t.task_type,
                   COUNT(*) AS n
            FROM execution_logs e
            JOIN tasks t ON e.task_id = t.id
            WHERE e.created_at >= {window_expr}
            GROUP BY e.model_id, t.task_type
            """
        ).fetchall()

    finally:
        conn.close()

    # ── Build per-model list ───────────────────────────────────────────────
    model_task_counts: dict[str, dict[str, int]] = {}
    for r in model_task_rows:
        mid = r["model_id"]
        if mid not in model_task_counts:
            model_task_counts[mid] = {}
        model_task_counts[mid][r["task_type"]] = int(r["n"])

    per_model = []
    for r in model_rows:
        mid = r["model_id"]
        per_model.append({
            "model_id":       mid,
            "executions":     int(r["executions"]),
            "success_rate":   round(float(r["success_rate"] or 0.0), 4),
            "avg_score":      round(float(r["avg_score"] or 0.0), 1),
            "avg_duration_ms": round(float(r["avg_duration_ms"] or 0.0), 0),
            "avg_retries":    round(float(r["avg_retries"] or 0.0), 2),
            "task_types":     model_task_counts.get(mid, {}),
        })

    # ── Build per-task-type list with recommendations ─────────────────────
    # Default model for each task type (from rule-based routing table)
    task_routing_defaults: dict[str, str] = {
        tt.value: cc.value for tt, cc in _TASK_ROUTING.items()
    }

    # Group cross_rows by task_type
    task_data: dict[str, list[dict]] = {}
    for r in cross_rows:
        tt = r["task_type"]
        if tt not in task_data:
            task_data[tt] = []
        task_data[tt].append({
            "model_id":     r["model_id"],
            "success_rate": round(float(r["success_rate"] or 0.0), 4),
            "n":            int(r["n"]),
        })

    per_task_type: list[dict] = []
    recommendations: list[str] = []

    for task_type_str, model_comparisons in task_data.items():
        default_model = task_routing_defaults.get(task_type_str, "fast_model")
        task_executions = sum(m["n"] for m in model_comparisons)

        task_entry: dict[str, Any] = {
            "task_type":        task_type_str,
            "default_model":    default_model,
            "executions":       task_executions,
            "models_compared":  model_comparisons,
            "recommendation":   None,
        }

        if task_executions < _REC_MIN_SAMPLES:
            task_entry["recommendation"] = (
                f"Insufficient data for {task_type_str} "
                f"(only {task_executions} executions) — no recommendation yet"
            )
        else:
            default_data = next(
                (m for m in model_comparisons if m["model_id"] == default_model),
                None,
            )
            if default_data:
                best = max(model_comparisons, key=lambda m: m["success_rate"])
                if best["model_id"] != default_model:
                    diff = best["success_rate"] - default_data["success_rate"]
                    if diff >= _ADAPTIVE_IMPROVEMENT_THRESHOLD and best["n"] >= _REC_MIN_SAMPLES:
                        diff_pp = round(diff * 100, 1)
                        rec = (
                            f"{best['model_id']} outperforms {default_model} by "
                            f"{diff_pp}pp for {task_type_str} "
                            f"(n={best['n']} vs n={default_data['n']}). "
                            f"Consider enabling adaptive_router_v2."
                        )
                        task_entry["recommendation"] = rec
                        recommendations.append(
                            f"Enable adaptive_router_v2 — {best['model_id']} shows "
                            f"{diff_pp}pp improvement on {task_type_str} tasks"
                        )

        per_task_type.append(task_entry)

    return {
        "generated_at":            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "window_days":             window_days,
        "total_executions":        total,
        "adaptive_router_enabled": is_feature_enabled("adaptive_router_v2"),
        "summary": {
            "overall_success_rate": round(overall_sr, 4),
            "overall_avg_score":    round(overall_avg_sc, 1),
            "models_active":        len(per_model),
            "task_types_seen":      len(task_data),
        },
        "per_model":        per_model,
        "per_task_type":    per_task_type,
        "recommendations":  recommendations,
    }
