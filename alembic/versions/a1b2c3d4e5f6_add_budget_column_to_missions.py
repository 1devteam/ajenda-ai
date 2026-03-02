"""add budget column to missions

Revision ID: a1b2c3d4e5f6
Revises: e1776d23c66e
Create Date: 2026-03-02 10:45:00.000000

The missions table was created without the budget column that is defined
in the Mission SQLAlchemy model. This migration adds the missing column.

Built with Pride for Obex Blackvault
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e1776d23c66e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add budget column to missions table."""
    op.add_column(
        "missions",
        sa.Column("budget", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Remove budget column from missions table."""
    op.drop_column("missions", "budget")
