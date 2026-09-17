"""Initial schema for Factory of Code

Revision ID: 001
Revises: None
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- Users
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Settings
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    -- Repos
    CREATE TABLE IF NOT EXISTS repos (
        id SERIAL PRIMARY KEY,
        gitlab_project_id INTEGER UNIQUE NOT NULL,
        name TEXT NOT NULL,
        full_path TEXT NOT NULL,
        clone_url_ssh TEXT NOT NULL,
        clone_url_http TEXT NOT NULL,
        default_branch TEXT NOT NULL DEFAULT 'main',
        last_synced_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Enums
    DO $$ BEGIN
        CREATE TYPE work_type AS ENUM ('feature','bugfix','refactor','migration','hotfix');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    DO $$ BEGIN
        CREATE TYPE run_status AS ENUM (
            'pending','running','awaiting_checkpoint','completed','failed','cancelled','rejected'
        );
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    DO $$ BEGIN
        CREATE TYPE step_status AS ENUM (
            'pending','running','completed','failed','skipped','rolled_back'
        );
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    DO $$ BEGIN
        CREATE TYPE checkpoint_status AS ENUM ('pending','approved','rejected');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    -- Pipeline Runs
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        repo_id INTEGER NOT NULL REFERENCES repos(id),
        base_branch TEXT NOT NULL DEFAULT 'main',
        work_branch TEXT NOT NULL DEFAULT '',
        work_type work_type NOT NULL,
        route TEXT NOT NULL,
        status run_status NOT NULL DEFAULT 'pending',
        current_step_idx INTEGER NOT NULL DEFAULT 0,
        risk_level TEXT DEFAULT 'low',
        final_verdict TEXT,
        mr_iid INTEGER,
        mr_url TEXT,
        rollback_count INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Pipeline Steps
    CREATE TABLE IF NOT EXISTS pipeline_steps (
        id SERIAL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
        agent_name TEXT NOT NULL,
        agent_number INTEGER NOT NULL,
        step_order INTEGER NOT NULL,
        status step_status NOT NULL DEFAULT 'pending',
        attempt INTEGER NOT NULL DEFAULT 1,
        output_summary TEXT DEFAULT '',
        verdict TEXT,
        metrics_json JSONB,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        duration_seconds REAL
    );

    -- Checkpoints
    CREATE TABLE IF NOT EXISTS checkpoints (
        id SERIAL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
        step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
        agent_name TEXT NOT NULL,
        reason TEXT NOT NULL,
        status checkpoint_status NOT NULL DEFAULT 'pending',
        reviewer_comment TEXT,
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Artifacts
    CREATE TABLE IF NOT EXISTS artifacts (
        id SERIAL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
        step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
        agent_name TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        git_commit_sha TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Step Logs
    CREATE TABLE IF NOT EXISTS step_logs (
        id SERIAL PRIMARY KEY,
        step_id INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
        chunk TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
    CREATE INDEX IF NOT EXISTS idx_pipeline_runs_repo ON pipeline_runs(repo_id);
    CREATE INDEX IF NOT EXISTS idx_pipeline_steps_run ON pipeline_steps(run_id);
    CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id);
    CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints(status);
    CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
    CREATE INDEX IF NOT EXISTS idx_step_logs_step ON step_logs(step_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS step_logs;
    DROP TABLE IF EXISTS artifacts;
    DROP TABLE IF EXISTS checkpoints;
    DROP TABLE IF EXISTS pipeline_steps;
    DROP TABLE IF EXISTS pipeline_runs;
    DROP TABLE IF EXISTS repos;
    DROP TABLE IF EXISTS settings;
    DROP TABLE IF EXISTS users;
    DROP TYPE IF EXISTS checkpoint_status;
    DROP TYPE IF EXISTS step_status;
    DROP TYPE IF EXISTS run_status;
    DROP TYPE IF EXISTS work_type;
    """)
