"""
Mission Control — Failure Clustering (Phase 3)
================================================
Groups failure_events by stack_trace_hash to identify recurring patterns.

A "cluster" is a set of failures sharing the same normalised stack trace.
When a new failure arrives with a known hash, its cluster's occurrence_count
is incremented and last_seen_at is updated.

Phase 3: hash-based clustering only.
Phase 5+: LLM-assisted cluster labelling + semantic similarity grouping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import FailureClusterRow, FailureClustersResponse

log = get_logger("codex.clustering")


class FailureClusterer:
    """
    Maintains failure_clusters table synced with failure_events.

    Lifecycle:
        clusterer = FailureClusterer()
        clusterer.upsert(stack_trace_hash)          # call after each failure_event insert
        clusters = clusterer.get_all(min_count=2)   # get recurring clusters
    """

    def upsert(
        self,
        stack_trace_hash: str,
        codex_candidate_id: Optional[str] = None,
    ) -> str:
        """
        Insert or update a failure cluster for this hash.
        Returns the cluster id.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM failure_clusters WHERE stack_trace_hash = ?",
                (stack_trace_hash,),
            ).fetchone()

            if existing:
                cluster_id = existing["id"]
                conn.execute(
                    """
                    UPDATE failure_clusters
                    SET occurrence_count = occurrence_count + 1,
                        last_seen_at = ?,
                        codex_candidate_id = COALESCE(?, codex_candidate_id)
                    WHERE id = ?
                    """,
                    (now, codex_candidate_id, cluster_id),
                )
                log.info(
                    "Failure cluster updated",
                    cluster_id=cluster_id,
                    hash=stack_trace_hash[:16],
                )
            else:
                cluster_id = str(ULID())
                conn.execute(
                    """
                    INSERT INTO failure_clusters
                        (id, stack_trace_hash, occurrence_count,
                         first_seen_at, last_seen_at, codex_candidate_id)
                    VALUES (?, ?, 1, ?, ?, ?)
                    """,
                    (cluster_id, stack_trace_hash, now, now, codex_candidate_id),
                )
                log.info(
                    "Failure cluster created",
                    cluster_id=cluster_id,
                    hash=stack_trace_hash[:16],
                )

            conn.commit()
            return cluster_id

        finally:
            conn.close()

    def label(self, cluster_id: str, label: str) -> None:
        """Set a human-readable label on a cluster."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE failure_clusters SET cluster_label = ? WHERE id = ?",
                (label, cluster_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all(
        self,
        min_count: int = 1,
        limit: int = 100,
        offset: int = 0,
    ) -> FailureClustersResponse:
        """Return all clusters with occurrence_count >= min_count."""
        conn = get_connection()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM failure_clusters WHERE occurrence_count >= ?",
                (min_count,),
            ).fetchone()["cnt"]

            rows = conn.execute(
                """
                SELECT id, stack_trace_hash, cluster_label, occurrence_count,
                       first_seen_at, last_seen_at, codex_candidate_id
                FROM failure_clusters
                WHERE occurrence_count >= ?
                ORDER BY occurrence_count DESC, last_seen_at DESC
                LIMIT ? OFFSET ?
                """,
                (min_count, limit, offset),
            ).fetchall()

            return FailureClustersResponse(
                clusters=[
                    FailureClusterRow(
                        id=r["id"],
                        stack_trace_hash=r["stack_trace_hash"],
                        cluster_label=r["cluster_label"],
                        occurrence_count=r["occurrence_count"],
                        first_seen_at=r["first_seen_at"],
                        last_seen_at=r["last_seen_at"],
                        codex_candidate_id=r["codex_candidate_id"],
                    )
                    for r in rows
                ],
                total=total,
            )
        finally:
            conn.close()

    def get_by_hash(self, stack_trace_hash: str) -> Optional[FailureClusterRow]:
        """Fetch a single cluster by hash."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM failure_clusters WHERE stack_trace_hash = ?",
                (stack_trace_hash,),
            ).fetchone()
            if row is None:
                return None
            return FailureClusterRow(
                id=row["id"],
                stack_trace_hash=row["stack_trace_hash"],
                cluster_label=row["cluster_label"],
                occurrence_count=row["occurrence_count"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                codex_candidate_id=row["codex_candidate_id"],
            )
        finally:
            conn.close()

    def rebuild_from_failure_events(self) -> int:
        """
        Rebuild failure_clusters from scratch by scanning failure_events.
        Useful after data import or if clusters table is stale.
        Returns number of clusters created/updated.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT stack_trace_hash,
                       COUNT(*) AS cnt,
                       MIN(created_at) AS first_seen,
                       MAX(created_at) AS last_seen
                FROM failure_events
                WHERE stack_trace_hash IS NOT NULL
                GROUP BY stack_trace_hash
                """
            ).fetchall()
        finally:
            conn.close()

        count = 0
        for row in rows:
            h = row["stack_trace_hash"]
            existing = self.get_by_hash(h)
            if existing is None:
                conn2 = get_connection()
                try:
                    conn2.execute(
                        """
                        INSERT OR IGNORE INTO failure_clusters
                            (id, stack_trace_hash, occurrence_count, first_seen_at, last_seen_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (str(ULID()), h, row["cnt"], row["first_seen"], row["last_seen"]),
                    )
                    conn2.commit()
                    count += 1
                finally:
                    conn2.close()

        log.info("Failure clusters rebuilt", count=count)
        return count


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_clusterer = FailureClusterer()


def upsert_cluster(hash_: str, candidate_id: Optional[str] = None) -> str:
    return _clusterer.upsert(hash_, codex_candidate_id=candidate_id)


def get_failure_clusters(min_count: int = 1, limit: int = 100, offset: int = 0) -> FailureClustersResponse:
    return _clusterer.get_all(min_count=min_count, limit=limit, offset=offset)
