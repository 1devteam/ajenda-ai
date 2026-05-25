"""expand evidence and outcome review lifecycle check constraints

Revision ID: 0020_expand_lifecycle_checks
Revises: 0019_harden_retrieval_values
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op

revision = "0020_expand_lifecycle_checks"
down_revision = "0019_harden_retrieval_values"
branch_labels = None
depends_on = None

EVIDENCE_TABLE = "evidence_records"
OUTCOME_TABLE = "outcome_reviews"

EVIDENCE_COLLECTION_STATUS_V1 = ("draft", "collected", "verified", "rejected", "superseded")
EVIDENCE_COLLECTION_STATUS_V2 = (
    "draft",
    "collected",
    "verified",
    "rejected",
    "superseded",
    "retention_hold",
    "archived",
    "purged",
)
OUTCOME_REVIEW_STATUS_V1 = ("draft", "in_review", "completed", "superseded")
OUTCOME_REVIEW_STATUS_V2 = ("draft", "in_review", "completed", "superseded", "escalated", "archived")
HUMAN_APPROVAL_STATUS_V1 = ("not_required", "pending", "approved", "rejected")
HUMAN_APPROVAL_STATUS_V2 = ("not_required", "pending", "approved", "rejected", "escalated")


def _in_check_sql(column: str, values: tuple[str, ...]) -> str:
    formatted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({formatted})"


def _nullable_in_check_sql(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {_in_check_sql(column, values)}"


def upgrade() -> None:
    op.drop_constraint("ck_evidence_records_collection_status", EVIDENCE_TABLE, type_="check")
    op.create_check_constraint(
        "ck_evidence_records_collection_status",
        EVIDENCE_TABLE,
        _in_check_sql("collection_status", EVIDENCE_COLLECTION_STATUS_V2),
    )

    op.drop_constraint("ck_outcome_reviews_review_status", OUTCOME_TABLE, type_="check")
    op.create_check_constraint(
        "ck_outcome_reviews_review_status",
        OUTCOME_TABLE,
        _in_check_sql("review_status", OUTCOME_REVIEW_STATUS_V2),
    )

    op.drop_constraint("ck_outcome_reviews_human_approval_status", OUTCOME_TABLE, type_="check")
    op.create_check_constraint(
        "ck_outcome_reviews_human_approval_status",
        OUTCOME_TABLE,
        _nullable_in_check_sql("human_approval_status", HUMAN_APPROVAL_STATUS_V2),
    )


def downgrade() -> None:
    op.drop_constraint("ck_outcome_reviews_human_approval_status", OUTCOME_TABLE, type_="check")
    op.create_check_constraint(
        "ck_outcome_reviews_human_approval_status",
        OUTCOME_TABLE,
        _nullable_in_check_sql("human_approval_status", HUMAN_APPROVAL_STATUS_V1),
    )

    op.drop_constraint("ck_outcome_reviews_review_status", OUTCOME_TABLE, type_="check")
    op.create_check_constraint(
        "ck_outcome_reviews_review_status",
        OUTCOME_TABLE,
        _in_check_sql("review_status", OUTCOME_REVIEW_STATUS_V1),
    )

    op.drop_constraint("ck_evidence_records_collection_status", EVIDENCE_TABLE, type_="check")
    op.create_check_constraint(
        "ck_evidence_records_collection_status",
        EVIDENCE_TABLE,
        _in_check_sql("collection_status", EVIDENCE_COLLECTION_STATUS_V1),
    )
