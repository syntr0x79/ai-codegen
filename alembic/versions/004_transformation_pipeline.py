"""Add transformation pipeline support

Revision ID: 004
Revises: 003
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TYPE work_type ADD VALUE IF NOT EXISTS 'transformation';
    ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS source_repo_id INTEGER REFERENCES repos(id);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE pipeline_runs DROP COLUMN IF EXISTS source_repo_id;
    """)
