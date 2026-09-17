import os
import tempfile
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://factory:factory@localhost:5433/factory_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# SQL from migration (inline for test independence from alembic)
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_presets (
    id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent_configs JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agent_prompts (
    agent_name TEXT PRIMARY KEY,
    system_prompt TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS repos (
    id SERIAL PRIMARY KEY, gitlab_project_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL, full_path TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    clone_url_ssh TEXT NOT NULL, clone_url_http TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    preset_id INTEGER REFERENCES agent_presets(id) ON DELETE SET NULL,
    last_synced_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$ BEGIN CREATE TYPE work_type AS ENUM ('feature','bugfix','refactor','migration','hotfix','transformation','devops'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE run_status AS ENUM ('pending','running','awaiting_checkpoint','completed','failed','cancelled','rejected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE step_status AS ENUM ('pending','running','completed','failed','skipped','rolled_back'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE checkpoint_status AS ENUM ('pending','approved','rejected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
    repo_id INTEGER NOT NULL REFERENCES repos(id),
    base_branch TEXT NOT NULL DEFAULT 'main', work_branch TEXT NOT NULL DEFAULT '',
    work_type work_type NOT NULL, route TEXT NOT NULL,
    status run_status NOT NULL DEFAULT 'pending',
    current_step_idx INTEGER NOT NULL DEFAULT 0, risk_level TEXT DEFAULT 'low',
    final_verdict TEXT, mr_iid INTEGER, mr_url TEXT,
    rollback_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    preset_snapshot JSONB,
    source_repo_id INTEGER REFERENCES repos(id),
    orchestrator_action TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pipeline_steps (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL, agent_number INTEGER NOT NULL,
    step_order INTEGER NOT NULL, status step_status NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 1, output_summary TEXT DEFAULT '',
    verdict TEXT, metrics_json JSONB,
    started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, duration_seconds REAL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL, reason TEXT NOT NULL,
    status checkpoint_status NOT NULL DEFAULT 'pending',
    reviewer_comment TEXT, reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS artifacts (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL, filename TEXT NOT NULL, file_path TEXT NOT NULL,
    git_commit_sha TEXT, storage_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS step_logs (
    id SERIAL PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    chunk TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    step_id INTEGER PRIMARY KEY REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    worker_id TEXT NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_TRUNCATE_SQL = """
TRUNCATE step_logs, worker_heartbeats, artifacts, checkpoints, pipeline_steps, pipeline_runs,
         repos, agent_presets, agent_prompts, settings, users RESTART IDENTITY CASCADE;
"""


@pytest_asyncio.fixture(scope="session")
async def _ensure_db():
    """Create test database if it doesn't exist, apply schema once."""
    # Connect to default 'factory' db to create test db if needed
    base_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/factory"
    try:
        conn = await asyncpg.connect(base_url)
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'factory_test'"
        )
        if not exists:
            await conn.execute("CREATE DATABASE factory_test")
        await conn.close()
    except Exception:
        pass  # DB might already exist or we're connecting directly to test DB

    conn = await asyncpg.connect(TEST_DATABASE_URL)
    await conn.execute(_SCHEMA_SQL)
    await conn.close()


@pytest_asyncio.fixture
async def db(_ensure_db):
    """Provide a Database instance with a clean state for each test."""
    from src.db import Database
    database = Database(TEST_DATABASE_URL)
    await database.init()
    # Clean all tables before each test
    await database._pool.execute(_TRUNCATE_SQL)
    yield database
    await database.close()


@pytest_asyncio.fixture
async def tmp_data_dir(tmp_path):
    os.environ["DATA_DIR"] = str(tmp_path)
    yield tmp_path


@pytest_asyncio.fixture
async def app(tmp_data_dir, _ensure_db):
    from src.db import Database
    from src.config import Config, load_agents_config
    from src.auth import AuthMiddleware, hash_password
    from fastapi import FastAPI, Request, Form
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
    from fastapi.staticfiles import StaticFiles

    config = Config()
    db = Database(config.database_url)
    await db.init()
    await db._pool.execute(_TRUNCATE_SQL)

    application = FastAPI(title="Factory of Code")
    application.state.db = db
    application.state.config = config

    # Ensure admin user
    admin = await db.get_user_by_username(config.admin_username)
    if not admin:
        await db.create_user(config.admin_username, hash_password(config.admin_password))

    # Pipeline
    try:
        agents_config = load_agents_config()
    except FileNotFoundError:
        agents_config = {"pipeline": {"max_iterations": 3, "max_concurrent_tasks": 2}}

    application.state.agents_config = agents_config
    application.state.gitlab = None
    application.state.minio = None

    # Auth middleware
    from src.auth import (
        AuthMiddleware, verify_password,
        create_session_cookie, decode_session_cookie,
    )
    application.add_middleware(AuthMiddleware, secret=config.secret_key)

    templates = Jinja2Templates(
        directory=Path(__file__).parent.parent / "src" / "templates"
    )

    @application.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str = ""):
        return templates.TemplateResponse(request, "login.html", {"error": error})

    @application.post("/auth/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        user = await db.get_user_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})
        response = RedirectResponse("/", status_code=303)
        cookie = create_session_cookie(user["id"], user["username"], config.secret_key)
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
        tasks = await db.list_runs()
        return templates.TemplateResponse(request, "dashboard.html", {
            "tasks": tasks, "user": request.state.user,
        })

    from src.api.runs import router as runs_router
    from src.api.transform import router as transform_router
    from src.api.checkpoints import router as checkpoints_router
    from src.api.repos import router as repos_router
    from src.api.presets import router as presets_router
    from src.api.prompts import router as prompts_router
    from src.api.settings import router as settings_router
    application.include_router(runs_router)
    application.include_router(transform_router)
    application.include_router(checkpoints_router)
    application.include_router(repos_router)
    application.include_router(presets_router)
    application.include_router(prompts_router)
    application.include_router(settings_router)

    yield application
    await db.close()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that is already logged in."""
    await client.post("/auth/login", data={
        "username": "admin",
        "password": "testpass",
    })
    yield client
