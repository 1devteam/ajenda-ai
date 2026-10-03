"""Allow the governed tenant-private application lifecycle state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_knowledge_apply"
down_revision = "0046_knowledge_change_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_knowledge_change_proposals_status", "knowledge_change_proposals", type_="check")
    op.create_check_constraint(
        "ck_knowledge_change_proposals_status",
        "knowledge_change_proposals",
        "status IN ('review_required', 'accepted', 'applied', 'rejected', 'superseded', 'rolled_back')",
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE knowledge_change_proposals SET status = 'accepted' WHERE status = 'applied'"))
    op.drop_constraint("ck_knowledge_change_proposals_status", "knowledge_change_proposals", type_="check")
    op.create_check_constraint(
        "ck_knowledge_change_proposals_status",
        "knowledge_change_proposals",
        "status IN ('review_required', 'accepted', 'rejected', 'superseded', 'rolled_back')",
    )
