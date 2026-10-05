"""Distinguish review rollback from compensating profile application reversion."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0048_profile_reversion"
down_revision = "0047_knowledge_apply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_business_profile_suggestions_status", "business_profile_suggestions", type_="check")
    op.create_check_constraint(
        "ck_business_profile_suggestions_status",
        "business_profile_suggestions",
        "status IN ('pending', 'approved', 'edited', 'declined', 'dismissed', 'superseded', 'review_rolled_back', 'application_reverted')",
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE business_profile_suggestions SET status = 'approved' "
            "WHERE status IN ('review_rolled_back', 'application_reverted')"
        )
    )
    op.drop_constraint("ck_business_profile_suggestions_status", "business_profile_suggestions", type_="check")
    op.create_check_constraint(
        "ck_business_profile_suggestions_status",
        "business_profile_suggestions",
        "status IN ('pending', 'approved', 'edited', 'declined', 'dismissed', 'superseded')",
    )
