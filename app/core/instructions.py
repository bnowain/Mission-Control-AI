"""
Mission Control — Persistent Instruction Layer (Phase 3)
==========================================================
Loads project-specific instructions and injects them into prompts.

Instruction types:
  - project_rule             — general project rules (e.g. "always use WAL mode")
  - naming_convention        — naming rules (e.g. "task_status not status")
  - architecture_constraint  — structural restrictions

Instructions are stored in the project_instructions table and versioned.
They are injected as system messages BEFORE the task prompt.

From Part 3 spec: these documents must be:
  - Versioned
  - Loaded before relevant tasks
  - Injected selectively (not always fully)
  - Summarized if exceeding context limits

Phase 3: full injection of active instructions.
Phase 5+: selective injection by relevance + summarization.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import InstructionType

log = get_logger("core.instructions")


class InstructionLoader:
    """
    Manages project_instructions CRUD and prompt injection.

    Usage:
        loader = InstructionLoader()
        loader.create(project_id, InstructionType.PROJECT_RULE, "Always use WAL mode.")
        messages = loader.inject(project_id, messages)
    """

    def create(
        self,
        project_id: str,
        instruction_type: InstructionType,
        content: str,
    ) -> str:
        """Insert a new instruction. Returns the new UUID id."""
        instruction_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO project_instructions
                    (id, project_id, instruction_type, content,
                     instruction_version, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (instruction_id, project_id, instruction_type.value, content, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        log.info(
            "Instruction created",
            id=instruction_id,
            project_id=project_id,
            instruction_type=instruction_type.value,
        )
        return instruction_id

    def get_active(
        self,
        project_id: str,
        instruction_type: Optional[InstructionType] = None,
    ) -> list[dict]:
        """Return all active instructions for a project (optionally filtered by type)."""
        conn = get_connection()
        try:
            if instruction_type:
                rows = conn.execute(
                    """
                    SELECT * FROM project_instructions
                    WHERE project_id = ? AND instruction_type = ? AND active = 1
                    ORDER BY instruction_type, instruction_version
                    """,
                    (project_id, instruction_type.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM project_instructions
                    WHERE project_id = ? AND active = 1
                    ORDER BY instruction_type, instruction_version
                    """,
                    (project_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def deactivate(self, instruction_id: str) -> None:
        """Soft-delete an instruction (set active=0). Never hard-delete."""
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE project_instructions SET active = 0, updated_at = ? WHERE id = ?",
                (now, instruction_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update(self, instruction_id: str, content: str) -> None:
        """
        Update instruction content and increment version.
        Old version is preserved (additive history via version increment).
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE project_instructions
                SET content = ?,
                    instruction_version = instruction_version + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (content, now, instruction_id),
            )
            conn.commit()
        finally:
            conn.close()

    def inject(
        self,
        project_id: str,
        messages: list[dict],
        instruction_type: Optional[InstructionType] = None,
    ) -> list[dict]:
        """
        Prepend project instructions as system messages into the message list.

        Injection order: project_rule → naming_convention → architecture_constraint.
        Returns the augmented message list (original is not mutated).
        """
        instructions = self.get_active(project_id, instruction_type)
        if not instructions:
            return messages

        # Group by type for structured injection
        by_type: dict[str, list[str]] = {}
        for inst in instructions:
            t = inst["instruction_type"]
            by_type.setdefault(t, []).append(inst["content"])

        injection_messages: list[dict] = []

        type_order = [
            InstructionType.PROJECT_RULE.value,
            InstructionType.NAMING_CONVENTION.value,
            InstructionType.ARCHITECTURE_CONSTRAINT.value,
        ]

        for t in type_order:
            contents = by_type.get(t, [])
            if contents:
                label = t.replace("_", " ").title()
                body = "\n".join(f"- {c}" for c in contents)
                injection_messages.append({
                    "role": "system",
                    "content": f"[{label}]\n{body}",
                })

        # Prepend after existing system messages, before user messages
        existing_system = [m for m in messages if m.get("role") == "system"]
        other = [m for m in messages if m.get("role") != "system"]

        augmented = existing_system + injection_messages + other

        log.info(
            "Instructions injected",
            project_id=project_id,
            injection_count=len(injection_messages),
            total_instructions=len(instructions),
        )
        return augmented


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_loader = InstructionLoader()


def inject_instructions(
    project_id: str,
    messages: list[dict],
    instruction_type: Optional[InstructionType] = None,
) -> list[dict]:
    """Convenience wrapper for InstructionLoader.inject()."""
    return _loader.inject(project_id, messages, instruction_type=instruction_type)


def create_instruction(
    project_id: str,
    instruction_type: InstructionType,
    content: str,
) -> str:
    """Convenience wrapper for InstructionLoader.create()."""
    return _loader.create(project_id, instruction_type, content)


def get_active_instructions(
    project_id: str,
    instruction_type: Optional[InstructionType] = None,
) -> list[dict]:
    """Convenience wrapper for InstructionLoader.get_active()."""
    return _loader.get_active(project_id, instruction_type=instruction_type)
