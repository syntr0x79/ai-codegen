"""Add MinIO storage_url, orchestrator_action, worker_heartbeats

Revision ID: 006
Revises: 005
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS storage_url TEXT;
    ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS orchestrator_action TEXT;

    CREATE TABLE IF NOT EXISTS worker_heartbeats (
        step_id INTEGER PRIMARY KEY REFERENCES pipeline_steps(id) ON DELETE CASCADE,
        worker_id TEXT NOT NULL,
        last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_heartbeats_time ON worker_heartbeats(last_heartbeat);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS worker_heartbeats;
    ALTER TABLE pipeline_runs DROP COLUMN IF EXISTS orchestrator_action;
    ALTER TABLE artifacts DROP COLUMN IF EXISTS storage_url;
    """)
