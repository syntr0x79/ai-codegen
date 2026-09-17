from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.pipeline.routes import get_route, route_to_string, route_from_string, AGENTS, get_agents_registry, AGENT_ARTIFACTS
from src.presets import build_preset_snapshot

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.post("/runs")
async def create_run(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    repo_id: int = Form(...),
    base_branch: str = Form("main"),
    work_type: str = Form(...),
):
    db = request.app.state.db
    user = request.state.user

    # Resolve preset for this repo
    preset_snapshot = None
    repo = await db.get_repo(repo_id)
    if repo and repo.get("preset_id"):
        preset = await db.get_preset(repo["preset_id"])
        preset_snapshot = build_preset_snapshot(
            getattr(request.app.state, "agents_config", {}), preset
        )

    try:
        route = get_route(work_type)
    except ValueError:
        return RedirectResponse("/runs/new?error=Invalid+work+type", status_code=303)
    run_id = await db.create_run(
        title=title, description=description,
        repo_id=repo_id, base_branch=base_branch,
        work_type=work_type, route=route_to_string(route),
        created_by=user["user_id"],
        preset_snapshot=preset_snapshot,
    )

    await db.update_run(run_id, orchestrator_action="start")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.get("/runs", response_class=HTMLResponse)
async def runs_list(request: Request):
    db = request.app.state.db
    runs = await db.list_runs()
    return templates.TemplateResponse(request, "runs.html", {
        "runs": runs, "user": request.state.user,
    })


@router.get("/runs/new", response_class=HTMLResponse)
async def new_run_page(request: Request):
    db = request.app.state.db
    repos = await db.list_repos()
    return templates.TemplateResponse(request, "run_new.html", {
        "repos": repos, "user": request.state.user,
    })


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: int):
    db = request.app.state.db
    run = await db.get_run(run_id)
    if not run:
        return RedirectResponse("/", status_code=303)

    steps = await db.get_steps(run_id)
    checkpoints = await db.list_checkpoints(run_id)
    artifacts = await db.get_artifacts(run_id)
    repo = await db.get_repo(run["repo_id"])

    route = route_from_string(run["route"])
    agents_reg = get_agents_registry(run["work_type"])
    route_agents = [(num, agents_reg[num]) for num in route]

    # Source repo for transformations
    source_repo = None
    if run.get("source_repo_id"):
        source_repo = await db.get_repo(run["source_repo_id"])

    # Pending checkpoint (if any)
    pending_cp = None
    for cp in checkpoints:
        if cp["status"] == "pending":
            pending_cp = cp
            break

    return templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "steps": steps, "checkpoints": checkpoints,
        "artifacts": artifacts, "repo": repo, "source_repo": source_repo,
        "route_agents": route_agents, "all_agents": agents_reg,
        "agent_artifacts": AGENT_ARTIFACTS,
        "pending_checkpoint": pending_cp,
        "user": request.state.user,
    })


@router.get("/runs/{run_id}/logs")
async def run_logs(request: Request, run_id: int):
    db = request.app.state.db
    steps = await db.get_steps(run_id)
    return [dict(s) for s in steps]


@router.get("/runs/{run_id}/status-check")
async def run_status_check(request: Request, run_id: int):
    """Status check with step info for live UI updates."""
    db = request.app.state.db
    run = await db.get_run(run_id)
    if not run:
        return {"status": "not_found"}
    steps = await db.get_steps(run_id)
    step_map = {}
    for s in steps:
        step_map[s["agent_name"]] = {
            "status": s["status"],
            "duration_seconds": s["duration_seconds"],
            "verdict": s["verdict"],
        }
    return {
        "status": run["status"],
        "current_step_idx": run["current_step_idx"],
        "steps": step_map,
    }


@router.get("/runs/{run_id}/steps/{step_id}/logs")
async def step_logs(request: Request, run_id: int, step_id: int):
    """Get logs for a specific step as plain text."""
    db = request.app.state.db
    logs = await db.get_step_logs(step_id)
    text = "".join(l["chunk"] for l in logs)
    return PlainTextResponse(text if text else "No logs yet")


@router.get("/runs/{run_id}/stream")
async def run_stream(request: Request, run_id: int):
    """SSE stream using pg_notify + DB polling. No in-memory state needed."""
    from sse_starlette.sse import EventSourceResponse
    import asyncpg

    db = request.app.state.db
    dsn = request.app.state.config.database_url

    async def event_generator():
        last_log_id = 0
        notify_event = asyncio.Event()
        listener_conn = None

        # Set up pg_notify listener on a dedicated connection
        try:
            listener_conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=10)

            def on_notification(conn, pid, channel, payload):
                notify_event.set()

            await listener_conn.add_listener("step_log", on_notification)
        except Exception:
            listener_conn = None  # Fallback to polling-only mode

        try:
            while True:
                # Check for new log entries
                chunks = await db.get_run_log_chunks_since(run_id, last_log_id)
                for chunk in chunks:
                    yield {"event": "log", "data": chunk["chunk"].rstrip("\n")}
                    last_log_id = chunk["id"]

                # Check if run is done
                run = await db.get_run(run_id)
                if run and run["status"] not in ("pending", "running", "awaiting_checkpoint"):
                    # Flush any remaining logs
                    final_chunks = await db.get_run_log_chunks_since(run_id, last_log_id)
                    for chunk in final_chunks:
                        yield {"event": "log", "data": chunk["chunk"].rstrip("\n")}
                    yield {"event": "done", "data": run["status"]}
                    break

                # Wait for notification or timeout
                notify_event.clear()
                try:
                    await asyncio.wait_for(notify_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if listener_conn:
                try:
                    await listener_conn.remove_listener("step_log", on_notification)
                    await listener_conn.close()
                except Exception:
                    pass

    return EventSourceResponse(event_generator())


@router.get("/runs/{run_id}/diff")
async def run_diff(request: Request, run_id: int):
    db = request.app.state.db
    run = await db.get_run(run_id)
    if not run:
        return PlainTextResponse("")

    # Try MinIO first
    minio = getattr(request.app.state, "minio", None)
    if minio:
        try:
            diff = minio.download_diff(run_id)
            if diff:
                return PlainTextResponse(diff)
        except Exception:
            pass

    # Fallback to filesystem
    from src.pipeline.git import get_diff
    repos_dir = request.app.state.config.repos_dir
    repo_dir = repos_dir / str(run_id)
    if not repo_dir.exists():
        return PlainTextResponse("Repository not available")

    diff = await get_diff(repo_dir, run["base_branch"])
    return PlainTextResponse(diff)


@router.get("/runs/{run_id}/artifacts/{filename:path}")
async def run_artifact(request: Request, run_id: int, filename: str):
    content = None
    db = request.app.state.db

    # Try 1: MinIO
    minio = getattr(request.app.state, "minio", None)
    if minio:
        try:
            content = minio.download_text(run_id, filename)
        except Exception:
            pass

    # Try 2: Filesystem
    if content is None:
        repos_dir = request.app.state.config.repos_dir
        filepath = repos_dir / str(run_id) / ".factory" / filename
        if filepath.exists():
            content = filepath.read_text()

    # Try 3: GitLab API (read file from work branch)
    if content is None:
        try:
            run = await db.get_run(run_id)
            if run:
                repo = await db.get_repo(run["repo_id"])
                gitlab = getattr(request.app.state, "gitlab", None)
                if repo and gitlab:
                    import urllib.parse
                    file_path = urllib.parse.quote(f".factory/{filename}", safe="")
                    branch = urllib.parse.quote(run["work_branch"], safe="")
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.get(
                            f"{gitlab.api_url}/projects/{repo['gitlab_project_id']}/repository/files/{file_path}/raw?ref={branch}",
                            headers={"PRIVATE-TOKEN": gitlab.token},
                        )
                        if resp.status_code == 200:
                            content = resp.text
        except Exception:
            pass

    if content is None:
        return HTMLResponse("<p style='color:#888;'>Not available yet</p>", status_code=404)

    html = _md_to_html(content)
    return HTMLResponse(f'<div class="artifact-rendered">{html}</div>')


@router.delete("/runs/{run_id}")
@router.post("/runs/{run_id}/cancel")
async def delete_run(request: Request, run_id: int):
    db = request.app.state.db
    run = await db.get_run(run_id)

    if run and run["status"] in ("running", "awaiting_checkpoint"):
        await db.update_run(run_id, status="cancelled", orchestrator_action="cancel")
    elif run:
        await db.delete_run(run_id)

    return RedirectResponse("/", status_code=303)


@router.post("/runs/{run_id}/restart")
async def restart_run(request: Request, run_id: int):
    """Restart a failed/cancelled/rejected run from the beginning."""
    db = request.app.state.db
    run = await db.get_run(run_id)
    if not run or run["status"] in ("pending", "running"):
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    # Clean up old repo directory
    from src.pipeline.git import cleanup_repo
    repos_dir = request.app.state.config.repos_dir
    repo_dir = repos_dir / str(run_id)
    await cleanup_repo(repo_dir)

    # Reset run state
    await db.update_run(
        run_id,
        status="pending",
        current_step_idx=0,
        rollback_count=0,
        final_verdict=None,
        mr_iid=None,
        mr_url=None,
    )

    # Signal orchestrator to start
    await db.update_run(run_id, orchestrator_action="start")

    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _md_to_html(text: str) -> str:
    """Minimal markdown to HTML: headers, code blocks, bold, lists, paragraphs."""
    lines = text.split("\n")
    html_lines = []
    in_code = False
    in_list = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                html_lines.append("</code></pre>")
                in_code = False
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            html_lines.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue

        stripped = line.strip()

        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h4>{stripped[4:]}</h4>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{stripped[3:]}</h3>")
            continue
        if stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{stripped[2:]}</h2>")
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            html_lines.append(f"<li>{content}</li>")
            continue
        if re.match(r'^\d+\.\s', stripped):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = re.sub(r'^\d+\.\s', '', stripped)
            content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            html_lines.append(f"<li>{content}</li>")
            continue

        if in_list and stripped == "":
            html_lines.append("</ul>")
            in_list = False

        if stripped == "":
            continue

        content = stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        html_lines.append(f"<p>{content}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_code:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)
