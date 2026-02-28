"""
Mission Control — Backfill Engine (Phase 4)
============================================
Finds artifacts processed with outdated pipeline versions and enqueues
reprocessing jobs.

simulate=True returns a plan without enqueuing anything.
"""

from __future__ import annotations

from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.processing.worker import enqueue_job

log = get_logger("processing.backfill")

BACKFILL_PRIORITY = 100  # lowest priority (large = lower priority)


class BackfillEngine:
    """
    Identifies and enqueues backfill jobs for stale artifact extractions.
    """

    def check_eligible(self, pipeline_name: str) -> list[dict]:
        """
        Find artifacts whose latest extraction for this pipeline is on an
        older engine_version than the current registered version.

        Returns list of:
            {artifact_id, current_version, target_version}
        """
        conn = get_connection()
        try:
            # Get current version for this pipeline
            current_ver_row = conn.execute(
                """
                SELECT engine_version FROM pipeline_versions
                WHERE pipeline_name = ? AND active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                (pipeline_name,),
            ).fetchone()

            if current_ver_row is None:
                log.info("No registered version for pipeline", pipeline_name=pipeline_name)
                return []

            target_version = current_ver_row["engine_version"]

            # Find artifacts with extractions on older versions
            rows = conn.execute(
                """
                SELECT ae.artifact_id, ae.pipeline_version AS current_version
                FROM artifacts_extracted ae
                WHERE ae.pipeline_name = ?
                  AND ae.pipeline_version != ?
                  AND ae.artifact_id = (
                      SELECT artifact_id FROM artifacts_extracted
                      WHERE artifact_id = ae.artifact_id AND pipeline_name = ?
                      ORDER BY created_at DESC LIMIT 1
                  )
                GROUP BY ae.artifact_id
                """,
                (pipeline_name, target_version, pipeline_name),
            ).fetchall()

            return [
                {
                    "artifact_id": r["artifact_id"],
                    "current_version": r["current_version"],
                    "target_version": target_version,
                }
                for r in rows
            ]
        finally:
            conn.close()

    def run_backfill(
        self,
        pipeline_name: str,
        simulate: bool = False,
    ) -> dict:
        """
        Find eligible artifacts and enqueue backfill jobs.
        If simulate=True, returns the plan without enqueuing.

        Returns:
            {pipeline_name, eligible_count, jobs_enqueued, simulated, artifacts}
        """
        eligible = self.check_eligible(pipeline_name)
        jobs_enqueued = 0

        if not simulate:
            for item in eligible:
                try:
                    enqueue_job(
                        job_type=pipeline_name,
                        artifact_id=item["artifact_id"],
                        priority=BACKFILL_PRIORITY,
                        payload={
                            "backfill": True,
                            "target_version": item["target_version"],
                        },
                        idempotency_key=f"backfill:{pipeline_name}:{item['artifact_id']}:{item['target_version']}",
                    )
                    jobs_enqueued += 1
                except Exception as exc:
                    log.warning(
                        "Failed to enqueue backfill job",
                        artifact_id=item["artifact_id"],
                        exc=str(exc),
                    )

        result = {
            "pipeline_name": pipeline_name,
            "eligible_count": len(eligible),
            "jobs_enqueued": jobs_enqueued,
            "simulated": simulate,
            "artifacts": eligible,
        }
        log.info(
            "Backfill run",
            pipeline_name=pipeline_name,
            eligible_count=len(eligible),
            jobs_enqueued=jobs_enqueued,
            simulated=simulate,
        )
        return result


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrappers
# ---------------------------------------------------------------------------

_engine = BackfillEngine()


def check_backfill_eligible(pipeline_name: str) -> list[dict]:
    return _engine.check_eligible(pipeline_name)


def run_backfill(pipeline_name: str, simulate: bool = False) -> dict:
    return _engine.run_backfill(pipeline_name, simulate=simulate)
