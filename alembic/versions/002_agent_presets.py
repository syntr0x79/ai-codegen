"""Add agent presets, repo preset_id, run preset_snapshot

Revision ID: 002
Revises: 001
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_presets (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        agent_configs JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    ALTER TABLE repos ADD COLUMN IF NOT EXISTS preset_id INTEGER REFERENCES agent_presets(id) ON DELETE SET NULL;
    ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS preset_snapshot JSONB;

    CREATE INDEX IF NOT EXISTS idx_repos_preset ON repos(preset_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS idx_repos_preset;
    ALTER TABLE pipeline_runs DROP COLUMN IF EXISTS preset_snapshot;
    ALTER TABLE repos DROP COLUMN IF EXISTS preset_id;
    DROP TABLE IF EXISTS agent_presets;
    """)
