from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.post("/runs/{run_id}/checkpoints/{cp_id}/approve")
async def approve_checkpoint(
    request: Request, run_id: int, cp_id: int,
    comment: str = Form(""),
):
    db = request.app.state.db
    user = request.state.user

    cp = await db.get_checkpoint(cp_id)
    if not cp or cp["run_id"] != run_id or cp["status"] != "pending":
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    await db.approve_checkpoint(cp_id, reviewed_by=user["user_id"], comment=comment)
    await db.update_run(run_id, orchestrator_action="resume")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/checkpoints/{cp_id}/reject")
async def reject_checkpoint(
    request: Request, run_id: int, cp_id: int,
    comment: str = Form(""),
):
    db = request.app.state.db
    user = request.state.user

    cp = await db.get_checkpoint(cp_id)
    if not cp or cp["run_id"] != run_id or cp["status"] != "pending":
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    await db.reject_checkpoint(cp_id, reviewed_by=user["user_id"], comment=comment)
    await db.update_run(run_id, status="rejected", final_verdict="Rejected by reviewer")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)
