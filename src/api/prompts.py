from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.pipeline.routes import AGENTS, TRANSFORM_AGENTS, DEVOPS_AGENTS

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request):
    db = request.app.state.db
    prompts = await db.get_all_agent_prompts()

    # Group agents by pipeline type
    agent_groups = [
        ("Standard Pipeline", {num: name for num, name in AGENTS.items()}),
        ("Transformation Pipeline", {num: name for num, name in TRANSFORM_AGENTS.items()}),
        ("DevOps Pipeline", {num: name for num, name in DEVOPS_AGENTS.items()}),
    ]

    return templates.TemplateResponse(request, "prompts.html", {
        "agent_groups": agent_groups,
        "prompts": prompts,
        "user": request.state.user,
    })


@router.put("/prompts/{agent_name}")
async def update_prompt(request: Request, agent_name: str):
    db = request.app.state.db
    data = await request.json()
    system_prompt = data.get("system_prompt", "").strip()
    if system_prompt:
        await db.set_agent_prompt(agent_name, system_prompt)
    return {"status": "ok"}


@router.post("/prompts/reset/{agent_name}")
async def reset_prompt(request: Request, agent_name: str):
    """Reset a prompt to the built-in default from .md file."""
    prompts_dir = Path(__file__).parent.parent / "prompts"

    # Check standard, transform, devops dirs
    for subdir in ["", "transform", "devops"]:
        prompt_file = prompts_dir / subdir / f"{agent_name}.md" if subdir else prompts_dir / f"{agent_name}.md"
        if prompt_file.exists():
            db = request.app.state.db
            await db.set_agent_prompt(agent_name, prompt_file.read_text())
            return {"status": "ok"}

    return {"status": "error", "error": "Default prompt file not found"}
