"""harden mission plan status values

Revision ID: 0018_harden_mission_plan_status
Revises: 0017_add_mission_plans
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op

revision = "0018_harden_mission_plan_status"
down_revision = "0017_add_mission_plans"
branch_labels = None
depends_on = None

MISSION_PLAN_STATUSES = ("draft", "ready", "superseded", "cancelled")
CONSTRAINT_NAME = "ck_mission_plans_status"
TABLE_NAME = "mission_plans"


def _status_check_sql() -> str:
    values = ", ".join(f"'{status}'" for status in MISSION_PLAN_STATUSES)
    return f"status IN ({values})"


def upgrade() -> None:
    op.create_check_constraint(CONSTRAINT_NAME, TABLE_NAME, _status_check_sql())


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
