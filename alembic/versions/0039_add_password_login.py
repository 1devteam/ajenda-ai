"""Add local password authentication for customer members."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_add_password_login"
down_revision = "0038_knowledge_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_members", sa.Column("password_hash", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_members", "password_hash")
