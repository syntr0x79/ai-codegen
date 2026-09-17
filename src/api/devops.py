from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.pipeline.routes import get_route, route_to_string
from src.presets import build_preset_snapshot

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/devops/new", response_class=HTMLResponse)
async def new_devops_page(request: Request):
    db = request.app.state.db
    repos = await db.list_repos()
    return templates.TemplateResponse(request, "devops_new.html", {
        "repos": repos, "user": request.state.user,
    })


@router.post("/devops")
async def create_devops(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    repo_id: int = Form(...),
):
    db = request.app.state.db
    user = request.state.user

    preset_snapshot = None
    repo = await db.get_repo(repo_id)
    if repo and repo.get("preset_id"):
        preset = await db.get_preset(repo["preset_id"])
        preset_snapshot = build_preset_snapshot(
            getattr(request.app.state, "agents_config", {}), preset
        )

    route = get_route("devops")
    run_id = await db.create_run(
        title=title, description=description,
        repo_id=repo_id, base_branch="main",
        work_type="devops", route=route_to_string(route),
        created_by=user["user_id"],
        preset_snapshot=preset_snapshot,
    )

    await db.update_run(run_id, orchestrator_action="start")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)
