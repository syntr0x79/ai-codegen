"""Add agent_prompts table and repo context column

Revision ID: 003
Revises: 002
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_prompts (
        agent_name TEXT PRIMARY KEY,
        system_prompt TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    ALTER TABLE repos ADD COLUMN IF NOT EXISTS context TEXT NOT NULL DEFAULT '';
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE repos DROP COLUMN IF EXISTS context;
    DROP TABLE IF EXISTS agent_prompts;
    """)
