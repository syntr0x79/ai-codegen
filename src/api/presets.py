from __future__ import annotations

import json

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.pipeline.routes import AGENTS

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()

AVAILABLE_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "Bash"]


@router.get("/presets", response_class=HTMLResponse)
async def presets_page(request: Request):
    db = request.app.state.db
    presets = await db.list_presets()
    return templates.TemplateResponse(request, "presets.html", {
        "presets": presets, "user": request.state.user,
    })


@router.get("/presets/new", response_class=HTMLResponse)
async def new_preset_page(request: Request):
    agents_config = getattr(request.app.state, "agents_config", {})
    return templates.TemplateResponse(request, "preset_edit.html", {
        "preset": None,
        "agents": {num: name for num, name in AGENTS.items()},
        "agents_config": agents_config,
        "available_tools": AVAILABLE_TOOLS,
        "user": request.state.user,
    })


@router.post("/presets")
async def create_preset(request: Request):
    db = request.app.state.db
    data = await request.json()
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    agent_configs = data.get("agent_configs", {})

    if not name:
        return {"error": "Name is required"}, 400

    preset_id = await db.create_preset(name, description, agent_configs)
    return {"id": preset_id, "redirect": f"/presets/{preset_id}"}


@router.get("/presets/{preset_id}", response_class=HTMLResponse)
async def edit_preset_page(request: Request, preset_id: int):
    db = request.app.state.db
    preset = await db.get_preset(preset_id)
    if not preset:
        return RedirectResponse("/presets", status_code=303)

    agents_config = getattr(request.app.state, "agents_config", {})
    return templates.TemplateResponse(request, "preset_edit.html", {
        "preset": preset,
        "agents": {num: name for num, name in AGENTS.items()},
        "agents_config": agents_config,
        "available_tools": AVAILABLE_TOOLS,
        "user": request.state.user,
    })


@router.put("/presets/{preset_id}")
async def update_preset(request: Request, preset_id: int):
    db = request.app.state.db
    data = await request.json()
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    agent_configs = data.get("agent_configs", {})

    await db.update_preset(preset_id, name, description, agent_configs)
    return {"status": "ok"}


@router.delete("/presets/{preset_id}")
@router.post("/presets/{preset_id}/delete")
async def delete_preset(request: Request, preset_id: int):
    db = request.app.state.db
    await db.delete_preset(preset_id)
    return RedirectResponse("/presets", status_code=303)


@router.post("/presets/{preset_id}/clone")
async def clone_preset(request: Request, preset_id: int):
    db = request.app.state.db
    preset = await db.get_preset(preset_id)
    if not preset:
        return RedirectResponse("/presets", status_code=303)

    new_name = f"{preset['name']} (copy)"
    new_id = await db.create_preset(new_name, preset["description"], preset["agent_configs"])
    return RedirectResponse(f"/presets/{new_id}", status_code=303)


@router.post("/repos/{repo_id}/preset")
async def set_repo_preset(request: Request, repo_id: int, preset_id: str = Form("")):
    db = request.app.state.db
    pid = int(preset_id) if preset_id else None
    await db.set_repo_preset(repo_id, pid)
    return RedirectResponse(f"/repos/{repo_id}", status_code=303)
