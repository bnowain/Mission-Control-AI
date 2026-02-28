"""
Mission Control — Prometheus Metrics Endpoint (Phase 8)
========================================================
GET /metrics  →  Prometheus text format

Metrics exposed:
  mc_task_count_total          — total tasks created
  mc_task_failures_total       — total tasks with passed=0
  mc_pipeline_jobs_total       — total processing jobs created
  mc_pipeline_jobs_queued      — jobs currently in QUEUED state
  mc_pipeline_jobs_running     — jobs currently in RUNNING state
  mc_audit_events_total        — total audit log entries
  mc_embeddings_total          — total RAG embedding chunks
  mc_codex_entries_total       — total promoted Codex entries
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.database.init import get_connection

router = APIRouter(tags=["observability"])


def _gauge(name: str, value: float | int, labels: dict | None = None) -> str:
    """Format a Prometheus gauge line."""
    label_str = ""
    if labels:
        pairs = ",".join(f'{k}="{v}"' for k, v in labels.items())
        label_str = f"{{{pairs}}}"
    return f"{name}{label_str} {value}"


def _collect_metrics() -> list[str]:
    lines: list[str] = []
    conn = get_connection()
    try:
        # ── Tasks ──────────────────────────────────────────────────────────────
        row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        task_total = row[0] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) FROM execution_logs WHERE passed = 0"
        ).fetchone()
        task_failures = row[0] if row else 0

        lines.append("# HELP mc_task_count_total Total tasks created")
        lines.append("# TYPE mc_task_count_total counter")
        lines.append(_gauge("mc_task_count_total", task_total))

        lines.append("# HELP mc_task_failures_total Total failed task executions")
        lines.append("# TYPE mc_task_failures_total counter")
        lines.append(_gauge("mc_task_failures_total", task_failures))

        # ── Pipeline jobs ─────────────────────────────────────────────────────
        row = conn.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()
        jobs_total = row[0] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE job_status = 'QUEUED'"
        ).fetchone()
        jobs_queued = row[0] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE job_status = 'RUNNING'"
        ).fetchone()
        jobs_running = row[0] if row else 0

        lines.append("# HELP mc_pipeline_jobs_total Total pipeline jobs created")
        lines.append("# TYPE mc_pipeline_jobs_total counter")
        lines.append(_gauge("mc_pipeline_jobs_total", jobs_total))

        lines.append("# HELP mc_pipeline_jobs_queued Jobs currently queued")
        lines.append("# TYPE mc_pipeline_jobs_queued gauge")
        lines.append(_gauge("mc_pipeline_jobs_queued", jobs_queued))

        lines.append("# HELP mc_pipeline_jobs_running Jobs currently running")
        lines.append("# TYPE mc_pipeline_jobs_running gauge")
        lines.append(_gauge("mc_pipeline_jobs_running", jobs_running))

        # ── Audit events ───────────────────────────────────────────────────────
        row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        audit_total = row[0] if row else 0

        lines.append("# HELP mc_audit_events_total Total immutable audit log entries")
        lines.append("# TYPE mc_audit_events_total counter")
        lines.append(_gauge("mc_audit_events_total", audit_total))

        # ── RAG embeddings ────────────────────────────────────────────────────
        try:
            row = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
            embed_total = row[0] if row else 0
        except Exception:
            embed_total = 0

        lines.append("# HELP mc_embeddings_total Total RAG embedding chunks stored")
        lines.append("# TYPE mc_embeddings_total gauge")
        lines.append(_gauge("mc_embeddings_total", embed_total))

        # ── Codex entries ─────────────────────────────────────────────────────
        try:
            row = conn.execute("SELECT COUNT(*) FROM master_codex").fetchone()
            codex_total = row[0] if row else 0
        except Exception:
            codex_total = 0

        lines.append("# HELP mc_codex_entries_total Total promoted Codex lessons")
        lines.append("# TYPE mc_codex_entries_total gauge")
        lines.append(_gauge("mc_codex_entries_total", codex_total))

        # ── Per-pipeline job counts ───────────────────────────────────────────
        try:
            rows = conn.execute(
                "SELECT pipeline_name, COUNT(*) as cnt FROM processing_jobs GROUP BY pipeline_name"
            ).fetchall()
            lines.append("# HELP mc_pipeline_jobs_by_type Jobs by pipeline type")
            lines.append("# TYPE mc_pipeline_jobs_by_type gauge")
            for r in rows:
                lines.append(_gauge("mc_pipeline_jobs_by_type", r[1], {"pipeline": r[0]}))
        except Exception:
            pass

    finally:
        conn.close()

    return lines


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """
    Prometheus-compatible metrics endpoint.
    Scrape with: prometheus.yml → scrape_configs → targets: ['localhost:8860']
    """
    lines = _collect_metrics()
    return "\n".join(lines) + "\n"
