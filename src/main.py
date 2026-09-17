from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.checkpoints import router as checkpoints_router
from src.api.devops import router as devops_router
from src.api.presets import router as presets_router
from src.api.prompts import router as prompts_router
from src.api.repos import router as repos_router
from src.api.runs import router as runs_router
from src.api.settings import router as settings_router
from src.api.transform import router as transform_router
from src.auth import (
    AuthMiddleware, hash_password, verify_password,
    create_session_cookie, decode_session_cookie,
)
from src.config import Config, load_agents_config
from src.db import Database
from src.gitlab_client import GitLabClient

_templates_dir = Path(__file__).parent / "templates"
_static_dir = Path(__file__).parent.parent / "static"
_prompts_dir = Path(__file__).parent / "prompts"
templates = Jinja2Templates(directory=_templates_dir)


async def _init_app_state(application: FastAPI) -> None:
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)

    import asyncio as _aio
    db = Database(config.database_url)
    for _attempt in range(30):
        try:
            await db.init()
            break
        except Exception:
            if _attempt < 29:
                await _aio.sleep(2)
            else:
                raise
    application.state.db = db
    application.state.config = config

    # Run Alembic migrations
    from alembic.config import Config as AlembicConfig
    from alembic import command
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)
    command.upgrade(alembic_cfg, "head")

    # Ensure admin user exists
    admin = await db.get_user_by_username(config.admin_username)
    if not admin:
        await db.create_user(config.admin_username, hash_password(config.admin_password))

    # Seed default presets and prompts
    from src.seed_presets import seed_default_presets, seed_default_prompts
    await seed_default_presets(db)
    await seed_default_prompts(db, _prompts_dir)

    # Restore credentials from DB (survives container restarts)
    from src.shared.credentials import restore_all_credentials
    await restore_all_credentials(db.get_setting)

    # MinIO
    from src.shared.minio_client import MinIOClient
    minio = MinIOClient(config.minio_endpoint, config.minio_access_key, config.minio_secret_key)
    try:
        minio.ensure_bucket()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MinIO init failed: {e}")
    application.state.minio = minio

    # Agents config (for presets UI, prompts page)
    try:
        agents_config = load_agents_config()
    except FileNotFoundError:
        agents_config = {"pipeline": {"max_concurrent_runs": 2, "max_rollbacks": 3}}
    application.state.agents_config = agents_config

    # GitLab client (for repos page)
    gitlab_url = config.gitlab_url
    gitlab_token = config.gitlab_token
    if not gitlab_token:
        db_gitlab_url = await db.get_setting("gitlab_url")
        db_gitlab_token = await db.get_setting("gitlab_token")
        if db_gitlab_token:
            gitlab_url = db_gitlab_url or gitlab_url
            gitlab_token = db_gitlab_token
    gitlab = GitLabClient(gitlab_url, gitlab_token) if gitlab_token else None
    application.state.gitlab = gitlab

    # NOTE: Pipeline is NOT initialized here anymore.
    # The Orchestrator service handles run execution.


def _register_routes(application: FastAPI) -> None:
    @application.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str = ""):
        return templates.TemplateResponse(request, "login.html", {"error": error})

    @application.post("/auth/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        db = request.app.state.db
        cfg = request.app.state.config
        user = await db.get_user_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})
        response = RedirectResponse("/", status_code=303)
        cookie = create_session_cookie(user["id"], user["username"], cfg.secret_key)
        response.set_cookie("session", cookie, httponly=True, max_age=86400 * 7)
        return response

    @application.post("/auth/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("session")
        return response

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    @application.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", {
            "user": request.state.user,
        })

    application.include_router(runs_router)
    application.include_router(transform_router)
    application.include_router(devops_router)
    application.include_router(checkpoints_router)
    application.include_router(repos_router)
    application.include_router(presets_router)
    application.include_router(prompts_router)
    application.include_router(settings_router)


@asynccontextmanager
async def lifespan(application: FastAPI):
    await _init_app_state(application)
    yield
    await application.state.db.close()


app = FastAPI(title="Factory of Code", lifespan=lifespan)
app.add_middleware(AuthMiddleware, secret=Config().secret_key)
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
_register_routes(app)
