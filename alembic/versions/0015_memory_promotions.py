"""memory promotions revision placeholder

Revision ID: 0015_memory_promotions
Revises: 0014_outcome_reviews
Create Date: 2026-05-10

This repository snapshot already treats memory promotion as the product layer
immediately preceding retrieval. The revision is intentionally schema-neutral so
0016_retrieval_contracts can preserve the durable migration order without
introducing memory-promotion behavior in this change.
"""

from __future__ import annotations

revision = "0015_memory_promotions"
down_revision = "0014_outcome_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
