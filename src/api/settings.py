from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.gitlab_client import GitLabError

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    db = request.app.state.db
    settings = await db.get_all_settings()
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "user": request.state.user,
    })


@router.put("/settings")
async def update_settings(request: Request):
    db = request.app.state.db
    data = await request.json()
    for key, value in data.items():
        await db.set_setting(key, str(value))

    # If GitLab settings changed, update the client
    gitlab_url = data.get("gitlab_url")
    gitlab_token = data.get("gitlab_token")
    if gitlab_url and gitlab_token:
        from src.gitlab_client import GitLabClient
        request.app.state.gitlab = GitLabClient(gitlab_url, gitlab_token)

    return {"status": "ok"}


@router.get("/api/gitlab/test")
async def test_gitlab(request: Request):
    gitlab = getattr(request.app.state, "gitlab", None)
    if not gitlab:
        return {"error": "GitLab not configured"}
    try:
        user = await gitlab.test_connection()
        return user
    except GitLabError as e:
        return {"error": f"GitLab API error: {e.detail}"}
    except Exception as e:
        return {"error": str(e)}


# ── Dashboard Stats ──

@router.get("/api/dashboard/stats")
async def dashboard_stats(request: Request):
    """Aggregated stats for the dashboard."""
    db = request.app.state.db
    stats = await db.get_dashboard_stats()

    # System metrics (from /proc/, works inside container)
    system = _get_system_metrics()
    stats["system"] = system

    return stats


def _get_system_metrics() -> dict:
    """Read CPU and memory from /proc/ (works in Docker containers)."""
    metrics = {"cpu_percent": 0, "memory_used_mb": 0, "memory_total_mb": 0}
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
            total_kb = meminfo.get("MemTotal", 0)
            available_kb = meminfo.get("MemAvailable", 0)
            metrics["memory_total_mb"] = round(total_kb / 1024)
            metrics["memory_used_mb"] = round((total_kb - available_kb) / 1024)
    except Exception:
        pass

    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()
            metrics["load_avg_1m"] = float(load[0])
            metrics["load_avg_5m"] = float(load[1])
    except Exception:
        pass

    try:
        import shutil
        usage = shutil.disk_usage("/")
        metrics["disk_total_gb"] = round(usage.total / (1024**3), 1)
        metrics["disk_used_gb"] = round(usage.used / (1024**3), 1)
        metrics["disk_free_gb"] = round(usage.free / (1024**3), 1)
    except Exception:
        pass

    return metrics


# ── Claude Auth ──

@router.get("/api/claude/status")
async def claude_status(request: Request):
    """Check Claude auth status from DB credentials."""
    db = request.app.state.db
    saved_creds = await db.get_setting("claude_credentials")
    if saved_creds:
        try:
            creds = json.loads(saved_creds)
            oauth = creds.get("claudeAiOauth", {})
            return {
                "loggedIn": bool(oauth.get("accessToken")),
                "authMethod": "claude.ai",
                "email": oauth.get("email"),
                "subscriptionType": oauth.get("subscriptionType"),
            }
        except (json.JSONDecodeError, KeyError):
            pass
    return {"loggedIn": False}


@router.post("/api/claude/login")
async def claude_login(request: Request):
    """Show credentials paste form (no CLI needed)."""
    return {"url": None, "status": "paste_credentials"}


@router.post("/api/claude/login/token")
async def claude_login_token(request: Request):
    """Save credentials to ~/.claude/.credentials.json.

    Accepts either:
    - Full JSON from .credentials.json (paste the whole file)
    - Just access_token + refresh_token fields
    """
    import os

    data = await request.json()
    credentials_json = data.get("credentials_json", "").strip()
    access_token = data.get("access_token", "").strip()
    refresh_token = data.get("refresh_token", "").strip()

    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    if credentials_json:
        # Full JSON paste
        try:
            creds = json.loads(credentials_json)
        except json.JSONDecodeError:
            return {"status": "error", "error": "Invalid JSON"}
    elif access_token:
        # Individual fields
        creds = {
            "claudeAiOauth": {
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "expiresAt": int((datetime.now(timezone.utc).timestamp() + 86400 * 30) * 1000),
                "scopes": [
                    "user:file_upload", "user:inference", "user:mcp_servers",
                    "user:profile", "user:sessions:claude_code",
                ],
            }
        }
    else:
        return {"status": "error", "error": "Provide credentials JSON or access token"}

    creds_json_str = json.dumps(creds, indent=2)
    from src.shared.credentials import write_claude_credentials
    write_claude_credentials(creds_json_str)

    db = request.app.state.db
    await db.set_setting("claude_credentials", creds_json_str)

    return {"status": "ok"}


@router.post("/api/claude/logout")
async def claude_logout(request: Request):
    """Clear saved credentials from DB."""
    db = request.app.state.db
    await db.set_setting("claude_credentials", "")
    return {"status": "ok"}


# ── Infrastructure Credentials ──

@router.post("/api/infra/ssh-key")
async def save_ssh_key(request: Request):
    """Save SSH private key to DB and filesystem."""
    data = await request.json()
    key = data.get("key", "").strip()
    if not key:
        return {"status": "error", "error": "Key is empty"}

    from src.shared.credentials import write_ssh_key
    write_ssh_key(key)
    db = request.app.state.db
    await db.set_setting("ssh_private_key", key)
    return {"status": "ok"}


@router.post("/api/infra/kubeconfig")
async def save_kubeconfig(request: Request):
    """Save kubeconfig to DB and filesystem."""
    data = await request.json()
    config = data.get("config", "").strip()
    if not config:
        return {"status": "error", "error": "Config is empty"}

    from src.shared.credentials import write_kubeconfig
    write_kubeconfig(config)
    db = request.app.state.db
    await db.set_setting("kubeconfig", config)
    return {"status": "ok"}


@router.get("/api/infra/status")
async def infra_status(request: Request):
    """Check if SSH key and kubeconfig are configured."""
    import os
    home = os.path.expanduser("~")
    ssh_exists = os.path.exists(os.path.join(home, ".ssh", "id_agent"))
    kube_exists = os.path.exists(os.path.join(home, ".kube", "config"))

    result = {"ssh_key": ssh_exists, "kubeconfig": kube_exists}

    if kube_exists:
        try:
            proc = await asyncio.create_subprocess_exec(
                "kubectl", "config", "get-contexts", "--no-headers", "-o", "name",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            result["kube_contexts"] = stdout.decode().strip().split("\n") if stdout else []
        except Exception:
            result["kube_contexts"] = []

    return result
