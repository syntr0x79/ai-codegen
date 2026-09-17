from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.pipeline.routes import get_route, route_to_string, TRANSFORM_AGENTS
from src.presets import build_preset_snapshot

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/transform/new", response_class=HTMLResponse)
async def new_transform_page(request: Request):
    db = request.app.state.db
    repos = await db.list_repos()
    return templates.TemplateResponse(request, "transform_new.html", {
        "repos": repos, "user": request.state.user,
    })


@router.post("/transform")
async def create_transform(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    repo_id: int = Form(...),
    source_repo_id: int = Form(...),
    base_branch: str = Form("main"),
):
    db = request.app.state.db
    user = request.state.user

    # Resolve preset for target repo
    preset_snapshot = None
    repo = await db.get_repo(repo_id)
    if repo and repo.get("preset_id"):
        preset = await db.get_preset(repo["preset_id"])
        preset_snapshot = build_preset_snapshot(
            getattr(request.app.state, "agents_config", {}), preset
        )

    route = get_route("transformation")
    run_id = await db.create_run(
        title=title, description=description,
        repo_id=repo_id, base_branch=base_branch,
        work_type="transformation", route=route_to_string(route),
        created_by=user["user_id"],
        preset_snapshot=preset_snapshot,
        source_repo_id=source_repo_id,
    )

    await db.update_run(run_id, orchestrator_action="start")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)
