"""Add devops work type

Revision ID: 005
Revises: 004
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE work_type ADD VALUE IF NOT EXISTS 'devops';")


def downgrade() -> None:
    pass  # Cannot remove enum values in PostgreSQL
