"""
Mission Control — Project Instructions API (Phase 3)
======================================================
POST /instructions          → create a project instruction
GET  /instructions/{project_id} → list active instructions for a project
DELETE /instructions/{id}   → deactivate (soft delete) an instruction
"""

from fastapi import APIRouter, HTTPException

from app.core.instructions import InstructionLoader, create_instruction, get_active_instructions
from app.database.async_helpers import run_in_thread
from app.models.schemas import InstructionCreate, InstructionResponse, InstructionType

router = APIRouter(prefix="/instructions", tags=["instructions"])

_loader = InstructionLoader()


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _create_sync(req: InstructionCreate) -> InstructionResponse:
    from app.database.init import get_connection
    instruction_id = create_instruction(
        project_id=req.project_id,
        instruction_type=req.instruction_type,
        content=req.content,
    )
    # Fetch the created row
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM project_instructions WHERE id = ?",
            (instruction_id,),
        ).fetchone()
        return InstructionResponse(
            id=row["id"],
            project_id=row["project_id"],
            instruction_type=InstructionType(row["instruction_type"]),
            content=row["content"],
            instruction_version=row["instruction_version"],
            active=bool(row["active"]),
            created_at=row["created_at"],
        )
    finally:
        conn.close()


def _list_sync(project_id: str) -> list[InstructionResponse]:
    rows = get_active_instructions(project_id)
    return [
        InstructionResponse(
            id=r["id"],
            project_id=r["project_id"],
            instruction_type=InstructionType(r["instruction_type"]),
            content=r["content"],
            instruction_version=r["instruction_version"],
            active=bool(r["active"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=InstructionResponse, status_code=201)
async def create_instruction_endpoint(req: InstructionCreate) -> InstructionResponse:
    """Create a new project instruction (project_rule, naming_convention, or architecture_constraint)."""
    return await run_in_thread(_create_sync, req)


@router.get("/{project_id}", response_model=list[InstructionResponse])
async def list_instructions(project_id: str) -> list[InstructionResponse]:
    """List all active instructions for a project."""
    return await run_in_thread(_list_sync, project_id)


@router.delete("/{instruction_id}", status_code=204)
async def deactivate_instruction(instruction_id: str) -> None:
    """Soft-delete an instruction (set active=0). Never hard-deleted."""
    await run_in_thread(_loader.deactivate, instruction_id)
