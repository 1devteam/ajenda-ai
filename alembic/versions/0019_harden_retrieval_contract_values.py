"""harden retrieval contract persisted values

Revision ID: 0019_harden_retrieval_values
Revises: 0018_harden_mission_plan_status
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op

revision = "0019_harden_retrieval_values"
down_revision = "0018_harden_mission_plan_status"
branch_labels = None
depends_on = None

TABLE_NAME = "retrieval_contracts"
RETRIEVAL_STATUSES = ("requested", "fulfilled", "rejected", "superseded", "revoked")
RETRIEVAL_STRATEGIES = ("semantic", "keyword", "hybrid", "operator_selected", "policy_selected", "procedural")


def _in_check_sql(column: str, values: tuple[str, ...]) -> str:
    formatted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({formatted})"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_retrieval_contracts_retrieval_status",
        TABLE_NAME,
        _in_check_sql("retrieval_status", RETRIEVAL_STATUSES),
    )
    op.create_check_constraint(
        "ck_retrieval_contracts_retrieval_strategy",
        TABLE_NAME,
        _in_check_sql("retrieval_strategy", RETRIEVAL_STRATEGIES),
    )


def downgrade() -> None:
    op.drop_constraint("ck_retrieval_contracts_retrieval_strategy", TABLE_NAME, type_="check")
    op.drop_constraint("ck_retrieval_contracts_retrieval_status", TABLE_NAME, type_="check")
