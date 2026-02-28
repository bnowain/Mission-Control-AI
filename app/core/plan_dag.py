"""
Mission Control — Plan DAG Engine (Phase 3)
=============================================
Implements the Plan → Phase → Step state machine.

Inspired by:
  - LangGraph CheckpointTuple: persistent state at each step (thread_id = plan_id)
  - CrewAI Flows @start/@listen/@router: event-driven transitions implemented
    natively as explicit state machine methods

State machine transitions:
  Plan:  pending → running → completed | failed | replanning
  Phase: pending → running → completed | failed
  Step:  pending → running → completed | failed | skipped

Dependency resolution:
  - A step can only run when all steps in its depends_on list are completed
  - Cycles are not detected (user responsibility to construct valid DAGs)

Replan:
  - Increments plan_version
  - Appends diff entry to plan_diff_history JSON
  - Resets failing phase/steps to pending
  - Saves checkpoint before and after replan

No new dependencies — uses only stdlib + existing project modules.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import (
    PhaseStatus,
    PlanCreate,
    PlanPhaseResponse,
    PlanResponse,
    PlanStatus,
    PlanStepResponse,
    StepStatus,
)

log = get_logger("core.plan_dag")


# ---------------------------------------------------------------------------
# Checkpoint store (LangGraph CheckpointTuple pattern — native)
# ---------------------------------------------------------------------------

class CheckpointStore:
    """Persists plan execution state to execution_checkpoints table."""

    def save(
        self,
        thread_id: str,
        checkpoint_key: str,
        state: dict,
        checkpoint_type: str = "step",
    ) -> str:
        """Upsert a checkpoint. Returns the checkpoint id."""
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM execution_checkpoints WHERE thread_id = ? AND checkpoint_key = ?",
                (thread_id, checkpoint_key),
            ).fetchone()

            if existing:
                checkpoint_id = existing["id"]
                conn.execute(
                    "UPDATE execution_checkpoints SET state_json = ?, created_at = ? WHERE id = ?",
                    (json.dumps(state), now, checkpoint_id),
                )
            else:
                checkpoint_id = str(ULID())
                conn.execute(
                    """
                    INSERT INTO execution_checkpoints
                        (id, thread_id, checkpoint_key, state_json, checkpoint_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (checkpoint_id, thread_id, checkpoint_key, json.dumps(state), checkpoint_type, now),
                )

            conn.commit()
            return checkpoint_id
        finally:
            conn.close()

    def load(self, thread_id: str, checkpoint_key: str) -> Optional[dict]:
        """Load a checkpoint. Returns None if not found."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT state_json FROM execution_checkpoints WHERE thread_id = ? AND checkpoint_key = ?",
                (thread_id, checkpoint_key),
            ).fetchone()
            return json.loads(row["state_json"]) if row else None
        finally:
            conn.close()

    def load_latest(self, thread_id: str) -> Optional[dict]:
        """Load the most recent checkpoint for a thread."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT state_json FROM execution_checkpoints WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
            return json.loads(row["state_json"]) if row else None
        finally:
            conn.close()


_checkpoint_store = CheckpointStore()


# ---------------------------------------------------------------------------
# DAG helper — dependency resolution
# ---------------------------------------------------------------------------

def _runnable_steps(steps: list[dict], completed_ids: set[str]) -> list[dict]:
    """Return steps that are pending and have all dependencies satisfied."""
    runnable = []
    for step in steps:
        if step["step_status"] != StepStatus.PENDING.value:
            continue
        deps = json.loads(step.get("depends_on") or "[]")
        if all(dep in completed_ids for dep in deps):
            runnable.append(step)
    return runnable


# ---------------------------------------------------------------------------
# Plan Engine
# ---------------------------------------------------------------------------

class PlanEngine:
    """
    Full Plan DAG lifecycle manager.

    Key methods:
        create_plan(req)           → PlanResponse
        get_plan(plan_id)          → PlanResponse
        execute_next_step(plan_id) → PlanStepResponse | None
        complete_step(step_id, ...)
        fail_step(step_id, ...)
        replan(plan_id, reason, new_phases)
    """

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_plan(self, req: PlanCreate) -> PlanResponse:
        """Create plan + phases + steps from a PlanCreate request."""
        now = datetime.now(timezone.utc).isoformat()
        plan_id = str(ULID())

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO plans (id, project_id, plan_title, plan_status, plan_version,
                                   plan_diff_history, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', 1, '[]', ?, ?)
                """,
                (plan_id, req.project_id, req.plan_title, now, now),
            )

            phase_responses: list[PlanPhaseResponse] = []
            for phase_idx, phase_req in enumerate(req.phases):
                phase_id = str(ULID())
                conn.execute(
                    """
                    INSERT INTO plan_phases (id, plan_id, phase_index, phase_title, phase_status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    """,
                    (phase_id, plan_id, phase_idx, phase_req.phase_title, now),
                )

                step_responses: list[PlanStepResponse] = []
                for step_idx, step_req in enumerate(phase_req.steps):
                    step_id = str(ULID())
                    conn.execute(
                        """
                        INSERT INTO plan_steps
                            (id, phase_id, plan_id, step_index, step_title, step_type,
                             step_status, step_prompt, depends_on, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                        """,
                        (
                            step_id, phase_id, plan_id, step_idx,
                            step_req.step_title, step_req.step_type,
                            step_req.step_prompt,
                            json.dumps(step_req.depends_on),
                            now, now,
                        ),
                    )
                    step_responses.append(PlanStepResponse(
                        id=step_id, phase_id=phase_id, plan_id=plan_id,
                        step_index=step_idx, step_title=step_req.step_title,
                        step_type=step_req.step_type, step_status=StepStatus.PENDING,
                        step_prompt=step_req.step_prompt,
                        depends_on=step_req.depends_on,
                        created_at=now, updated_at=now,
                    ))

                phase_responses.append(PlanPhaseResponse(
                    id=phase_id, plan_id=plan_id, phase_index=phase_idx,
                    phase_title=phase_req.phase_title, phase_status=PhaseStatus.PENDING,
                    steps=step_responses, created_at=now,
                ))

            conn.commit()

        finally:
            conn.close()

        # Save initial checkpoint
        _checkpoint_store.save(
            thread_id=plan_id,
            checkpoint_key="plan_created",
            state={"plan_id": plan_id, "status": "pending"},
            checkpoint_type="plan",
        )

        log.info("Plan created", plan_id=plan_id, phases=len(req.phases))

        return PlanResponse(
            id=plan_id, project_id=req.project_id, plan_title=req.plan_title,
            plan_status=PlanStatus.PENDING, plan_version=1, plan_diff_history=[],
            phases=phase_responses, created_at=now, updated_at=now,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_plan(self, plan_id: str) -> Optional[PlanResponse]:
        """Fetch a complete plan with all phases and steps."""
        conn = get_connection()
        try:
            plan_row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if plan_row is None:
                return None

            phases = conn.execute(
                "SELECT * FROM plan_phases WHERE plan_id = ? ORDER BY phase_index",
                (plan_id,),
            ).fetchall()

            phase_responses = []
            for phase in phases:
                steps = conn.execute(
                    "SELECT * FROM plan_steps WHERE phase_id = ? ORDER BY step_index",
                    (phase["id"],),
                ).fetchall()

                step_responses = [
                    PlanStepResponse(
                        id=s["id"], phase_id=s["phase_id"], plan_id=s["plan_id"],
                        step_index=s["step_index"], step_title=s["step_title"],
                        step_type=s["step_type"],
                        step_status=StepStatus(s["step_status"]),
                        step_prompt=s["step_prompt"],
                        depends_on=json.loads(s["depends_on"] or "[]"),
                        task_id=s["task_id"],
                        result_summary=s["result_summary"],
                        created_at=s["created_at"], updated_at=s["updated_at"],
                    )
                    for s in steps
                ]

                phase_responses.append(PlanPhaseResponse(
                    id=phase["id"], plan_id=phase["plan_id"],
                    phase_index=phase["phase_index"], phase_title=phase["phase_title"],
                    phase_status=PhaseStatus(phase["phase_status"]),
                    steps=step_responses, created_at=phase["created_at"],
                ))

            diff_history = json.loads(plan_row["plan_diff_history"] or "[]")

            return PlanResponse(
                id=plan_row["id"], project_id=plan_row["project_id"],
                plan_title=plan_row["plan_title"],
                plan_status=PlanStatus(plan_row["plan_status"]),
                plan_version=plan_row["plan_version"],
                plan_diff_history=diff_history,
                phases=phase_responses,
                created_at=plan_row["created_at"],
                updated_at=plan_row["updated_at"],
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Execution — @start / @listen / @router pattern (native)
    # ------------------------------------------------------------------

    def start_plan(self, plan_id: str) -> bool:
        """
        @start — transition plan pending → running.
        Returns True if started; False if already running/complete.
        """
        return self._set_plan_status(plan_id, PlanStatus.RUNNING, from_status=PlanStatus.PENDING)

    def get_next_runnable_step(self, plan_id: str) -> Optional[dict]:
        """
        @listen — return the next runnable step (pending + deps satisfied).
        Returns the raw DB row dict, or None if no steps are runnable.
        """
        conn = get_connection()
        try:
            # Find first pending phase
            phases = conn.execute(
                "SELECT * FROM plan_phases WHERE plan_id = ? AND phase_status IN ('pending','running') ORDER BY phase_index",
                (plan_id,),
            ).fetchall()

            for phase in phases:
                steps = conn.execute(
                    "SELECT * FROM plan_steps WHERE phase_id = ? ORDER BY step_index",
                    (phase["id"],),
                ).fetchall()
                steps_dicts = [dict(s) for s in steps]

                completed_ids = {s["id"] for s in steps_dicts if s["step_status"] == "completed"}
                runnable = _runnable_steps(steps_dicts, completed_ids)

                if runnable:
                    # @router: pick the first runnable step
                    return runnable[0]

                # If all steps in this phase are done, move to next phase
                all_done = all(
                    s["step_status"] in ("completed", "skipped") for s in steps_dicts
                )
                if not all_done:
                    # Phase has remaining non-runnable steps (blocked) — stall
                    return None

            return None  # All phases complete
        finally:
            conn.close()

    def execute_next_step(self, plan_id: str) -> Optional[PlanStepResponse]:
        """
        High-level: mark the next runnable step as 'running' and return it.
        Returns None if no step is runnable (plan complete or blocked).
        """
        step_dict = self.get_next_runnable_step(plan_id)
        if step_dict is None:
            return None

        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE plan_steps SET step_status = 'running', updated_at = ? WHERE id = ?",
                (now, step_dict["id"]),
            )
            # Mark phase as running if pending
            conn.execute(
                "UPDATE plan_phases SET phase_status = 'running' WHERE id = ? AND phase_status = 'pending'",
                (step_dict["phase_id"],),
            )
            # Mark plan as running if pending
            conn.execute(
                "UPDATE plans SET plan_status = 'running', updated_at = ? WHERE id = ? AND plan_status = 'pending'",
                (now, plan_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Save checkpoint
        _checkpoint_store.save(
            thread_id=plan_id,
            checkpoint_key=step_dict["id"],
            state={
                "plan_id": plan_id,
                "step_id": step_dict["id"],
                "step_title": step_dict["step_title"],
                "step_status": "running",
            },
            checkpoint_type="step",
        )

        return PlanStepResponse(
            id=step_dict["id"], phase_id=step_dict["phase_id"], plan_id=plan_id,
            step_index=step_dict["step_index"], step_title=step_dict["step_title"],
            step_type=step_dict["step_type"], step_status=StepStatus.RUNNING,
            step_prompt=step_dict["step_prompt"],
            depends_on=json.loads(step_dict.get("depends_on") or "[]"),
            task_id=step_dict.get("task_id"),
            created_at=step_dict["created_at"], updated_at=now,
        )

    def complete_step(
        self,
        step_id: str,
        result_summary: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        """Mark a step as completed. Cascades to phase + plan if fully done."""
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE plan_steps
                SET step_status = 'completed', result_summary = ?, task_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (result_summary, task_id, now, step_id),
            )

            step_row = conn.execute("SELECT plan_id, phase_id FROM plan_steps WHERE id = ?", (step_id,)).fetchone()
            if step_row:
                self._maybe_complete_phase(conn, step_row["phase_id"], now)
                self._maybe_complete_plan(conn, step_row["plan_id"], now)

            conn.commit()
        finally:
            conn.close()

        # Update checkpoint
        _checkpoint_store.save(
            thread_id=step_id,  # re-use step_id in checkpoint key
            checkpoint_key=step_id,
            state={"step_id": step_id, "step_status": "completed", "result_summary": result_summary},
            checkpoint_type="step",
        )

    def fail_step(self, step_id: str, reason: Optional[str] = None) -> None:
        """Mark a step as failed. Cascades to phase + plan."""
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE plan_steps SET step_status = 'failed', result_summary = ?, updated_at = ? WHERE id = ?",
                (reason, now, step_id),
            )
            step_row = conn.execute("SELECT plan_id, phase_id FROM plan_steps WHERE id = ?", (step_id,)).fetchone()
            if step_row:
                conn.execute(
                    "UPDATE plan_phases SET phase_status = 'failed' WHERE id = ?",
                    (step_row["phase_id"],),
                )
                conn.execute(
                    "UPDATE plans SET plan_status = 'failed', updated_at = ? WHERE id = ?",
                    (now, step_row["plan_id"]),
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Replan
    # ------------------------------------------------------------------

    def replan(
        self,
        plan_id: str,
        reason: str,
        new_phases: Optional[list] = None,
    ) -> PlanResponse:
        """
        Trigger a replan cycle:
          1. Increment plan_version
          2. Append diff entry to plan_diff_history
          3. If new_phases provided: reset failed phases/steps and add new ones
          4. Set plan_status back to 'running'
          5. Save checkpoint
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            plan_row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if plan_row is None:
                raise ValueError(f"Plan '{plan_id}' not found.")

            old_version = plan_row["plan_version"]
            new_version = old_version + 1
            diff_history = json.loads(plan_row["plan_diff_history"] or "[]")

            diff_entry = {
                "version": new_version,
                "diff": reason,
                "changed_at": now,
            }
            diff_history.append(diff_entry)

            conn.execute(
                """
                UPDATE plans
                SET plan_status = 'replanning', plan_version = ?, plan_diff_history = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_version, json.dumps(diff_history), now, plan_id),
            )

            # Reset failed steps to pending so they can retry
            conn.execute(
                """
                UPDATE plan_steps SET step_status = 'pending', updated_at = ?
                WHERE plan_id = ? AND step_status = 'failed'
                """,
                (now, plan_id),
            )
            conn.execute(
                "UPDATE plan_phases SET phase_status = 'pending' WHERE plan_id = ? AND phase_status = 'failed'",
                (plan_id,),
            )

            # Add new phases if provided
            if new_phases:
                # Find current max phase_index
                max_idx_row = conn.execute(
                    "SELECT MAX(phase_index) AS mx FROM plan_phases WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
                start_idx = (max_idx_row["mx"] or 0) + 1

                for offset, phase_req in enumerate(new_phases):
                    phase_id = str(ULID())
                    conn.execute(
                        "INSERT INTO plan_phases (id, plan_id, phase_index, phase_title, phase_status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                        (phase_id, plan_id, start_idx + offset, phase_req.phase_title if hasattr(phase_req, 'phase_title') else str(phase_req), now),
                    )

            # Set plan back to running
            conn.execute(
                "UPDATE plans SET plan_status = 'running', updated_at = ? WHERE id = ?",
                (now, plan_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Save replan checkpoint
        _checkpoint_store.save(
            thread_id=plan_id,
            checkpoint_key=f"replan_v{new_version}",
            state={"plan_id": plan_id, "version": new_version, "reason": reason},
            checkpoint_type="plan",
        )

        log.info("Replan executed", plan_id=plan_id, version=new_version, reason=reason)
        return self.get_plan(plan_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_plan_status(
        self, plan_id: str, new_status: PlanStatus, from_status: Optional[PlanStatus] = None
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            if from_status:
                cur = conn.execute("SELECT plan_status FROM plans WHERE id = ?", (plan_id,)).fetchone()
                if cur is None or cur["plan_status"] != from_status.value:
                    return False

            conn.execute(
                "UPDATE plans SET plan_status = ?, updated_at = ? WHERE id = ?",
                (new_status.value, now, plan_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def _maybe_complete_phase(conn, phase_id: str, now: str) -> None:
        steps = conn.execute(
            "SELECT step_status FROM plan_steps WHERE phase_id = ?", (phase_id,)
        ).fetchall()
        if all(s["step_status"] in ("completed", "skipped") for s in steps):
            conn.execute(
                "UPDATE plan_phases SET phase_status = 'completed' WHERE id = ?",
                (phase_id,),
            )

    @staticmethod
    def _maybe_complete_plan(conn, plan_id: str, now: str) -> None:
        phases = conn.execute(
            "SELECT phase_status FROM plan_phases WHERE plan_id = ?", (plan_id,)
        ).fetchall()
        if all(p["phase_status"] == "completed" for p in phases):
            conn.execute(
                "UPDATE plans SET plan_status = 'completed', updated_at = ? WHERE id = ?",
                (now, plan_id),
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine = PlanEngine()


def create_plan(req: PlanCreate) -> PlanResponse:
    return _engine.create_plan(req)


def get_plan(plan_id: str) -> Optional[PlanResponse]:
    return _engine.get_plan(plan_id)


def execute_next_step(plan_id: str) -> Optional[PlanStepResponse]:
    return _engine.execute_next_step(plan_id)


def complete_step(step_id: str, result_summary: Optional[str] = None, task_id: Optional[str] = None) -> None:
    return _engine.complete_step(step_id, result_summary=result_summary, task_id=task_id)


def fail_step(step_id: str, reason: Optional[str] = None) -> None:
    return _engine.fail_step(step_id, reason=reason)


def replan(plan_id: str, reason: str, new_phases=None) -> PlanResponse:
    return _engine.replan(plan_id, reason=reason, new_phases=new_phases)
