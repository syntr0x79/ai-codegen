from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.gitlab_client import GitLabError

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/repos", response_class=HTMLResponse)
async def repos_page(request: Request):
    db = request.app.state.db
    repos = await db.list_repos()
    return templates.TemplateResponse(request, "repos.html", {
        "repos": repos, "user": request.state.user,
    })


@router.post("/repos/connect")
async def connect_repo(request: Request, gitlab_project_id: int = Form(...)):
    db = request.app.state.db
    gitlab = getattr(request.app.state, "gitlab", None)
    if not gitlab:
        return RedirectResponse("/repos?error=GitLab+not+configured", status_code=303)

    existing = await db.get_repo_by_gitlab_id(gitlab_project_id)
    if existing:
        return RedirectResponse(f"/repos/{existing['id']}", status_code=303)

    try:
        project = await gitlab.get_project(gitlab_project_id)
    except GitLabError:
        return RedirectResponse("/repos?error=Project+not+found", status_code=303)

    repo_id = await db.create_repo(
        gitlab_project_id=project["id"],
        name=project["name"],
        full_path=project["full_path"],
        clone_url_ssh=project["clone_url_ssh"],
        clone_url_http=project["clone_url_http"],
        default_branch=project["default_branch"],
    )
    return RedirectResponse(f"/repos/{repo_id}", status_code=303)


@router.get("/repos/{repo_id}", response_class=HTMLResponse)
async def repo_detail(request: Request, repo_id: int):
    db = request.app.state.db
    repo = await db.get_repo(repo_id)
    if not repo:
        return RedirectResponse("/repos", status_code=303)

    # Fetch branches from GitLab
    branches = []
    gitlab = getattr(request.app.state, "gitlab", None)
    if gitlab and repo.get("gitlab_project_id"):
        try:
            branches = await gitlab.list_branches(repo["gitlab_project_id"])
        except GitLabError:
            pass

    # Recent runs for this repo
    runs = await db.list_runs(repo_id=repo_id)

    # Presets for selector
    presets = await db.list_presets()

    return templates.TemplateResponse(request, "repo_detail.html", {
        "repo": repo, "branches": branches, "runs": runs,
        "presets": presets, "user": request.state.user,
    })


@router.delete("/repos/{repo_id}")
@router.post("/repos/{repo_id}/disconnect")
async def disconnect_repo(request: Request, repo_id: int):
    db = request.app.state.db

    # Check for active runs
    runs = await db.list_runs(repo_id=repo_id)
    active = [r for r in runs if r["status"] in ("pending", "running", "awaiting_checkpoint")]
    if active:
        return RedirectResponse(f"/repos/{repo_id}?error=Cannot+disconnect:+has+active+runs", status_code=303)

    # Delete associated runs (FK constraint on repo_id)
    for run in runs:
        await db.delete_run(run["id"])

    # Clear source_repo_id references (FK constraint on source_repo_id)
    await db._pool.execute(
        "UPDATE pipeline_runs SET source_repo_id = NULL WHERE source_repo_id = $1",
        repo_id,
    )

    await db.delete_repo(repo_id)
    return RedirectResponse("/repos", status_code=303)


@router.post("/repos/{repo_id}/sync")
async def sync_repo(request: Request, repo_id: int):
    db = request.app.state.db
    repo = await db.get_repo(repo_id)
    if not repo:
        return RedirectResponse("/repos", status_code=303)

    gitlab = getattr(request.app.state, "gitlab", None)
    if not gitlab:
        return RedirectResponse(f"/repos/{repo_id}?error=GitLab+not+configured", status_code=303)

    try:
        project = await gitlab.get_project(repo["gitlab_project_id"])
        await db.update_repo_sync(
            repo_id,
            name=project["name"],
            full_path=project["full_path"],
            clone_url_ssh=project["clone_url_ssh"],
            clone_url_http=project["clone_url_http"],
            default_branch=project["default_branch"],
        )
    except GitLabError:
        pass

    return RedirectResponse(f"/repos/{repo_id}", status_code=303)


@router.post("/repos/{repo_id}/context")
async def save_repo_context(request: Request, repo_id: int, context: str = Form("")):
    db = request.app.state.db
    await db.update_repo_sync(repo_id, context=context)
    return RedirectResponse(f"/repos/{repo_id}", status_code=303)


# ── GitLab project search (JSON, for HTMX) ──

@router.get("/api/gitlab/projects")
async def search_gitlab_projects(request: Request, search: str = ""):
    gitlab = getattr(request.app.state, "gitlab", None)
    if not gitlab:
        return []
    try:
        return await gitlab.list_projects(search=search)
    except GitLabError:
        return []


@router.get("/api/repos/{repo_id}/branches")
async def repo_branches(request: Request, repo_id: int):
    """JSON endpoint for HTMX branch dropdowns."""
    db = request.app.state.db
    repo = await db.get_repo(repo_id)
    if not repo:
        return []

    gitlab = getattr(request.app.state, "gitlab", None)
    if not gitlab:
        return []
    try:
        return await gitlab.list_branches(repo["gitlab_project_id"])
    except GitLabError:
        return []
