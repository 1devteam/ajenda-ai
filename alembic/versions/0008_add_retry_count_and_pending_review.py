"""Add retry_count to execution_tasks and pending_review to task status constraint.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-07

Changes:
  - execution_tasks.retry_count (INTEGER, NOT NULL, DEFAULT 0)
      Tracks how many times a task has been recovered and re-queued by the
      RuntimeMaintainer. When retry_count reaches max_retries the task is
      dead-lettered instead of re-queued.

  - Drop and recreate ck_execution_tasks_status CHECK constraint to add the
      'pending_review' value, enabling the PolicyGuardian PENDING_REVIEW state.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Full set of allowed task status values after this migration
_TASK_STATES_V2 = (
    "planned",
    "queued",
    "claimed",
    "running",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "dead_lettered",
    "recovering",
    "pending_review",
)


def upgrade() -> None:
    # 1. Add retry_count column with default 0 (backfills existing rows)
    op.add_column(
        "execution_tasks",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment=(
                "Number of times this task has been retried after failure or lease expiry. "
                "Incremented by RuntimeMaintainer on each recovering->queued re-enqueue."
            ),
        ),
    )

    # 2. Drop the old CHECK constraint and recreate with pending_review included
    op.drop_constraint("ck_execution_tasks_status", "execution_tasks", type_="check")
    formatted = ", ".join(f"'{v}'" for v in _TASK_STATES_V2)
    op.create_check_constraint(
        "ck_execution_tasks_status",
        "execution_tasks",
        f"status IN ({formatted})",
    )


def downgrade() -> None:
    # Restore the original CHECK constraint (without pending_review)
    _TASK_STATES_V1 = (
        "planned",
        "queued",
        "claimed",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
        "dead_lettered",
        "recovering",
    )
    op.drop_constraint("ck_execution_tasks_status", "execution_tasks", type_="check")
    formatted = ", ".join(f"'{v}'" for v in _TASK_STATES_V1)
    op.create_check_constraint(
        "ck_execution_tasks_status",
        "execution_tasks",
        f"status IN ({formatted})",
    )

    # Remove retry_count column
    op.drop_column("execution_tasks", "retry_count")
