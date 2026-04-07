"""Add 'recovering' state to execution_tasks and update check constraint.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-03

Why 'recovering'?
-----------------
The current task state machine has a gap in the lease-expiry recovery path.
When a worker dies mid-execution and its lease expires, the RuntimeMaintainer
requeues the task from 'running' → 'queued'. This is correct but loses the
information that the task was previously in-flight and is being recovered.

The 'recovering' state provides:
1. Observability: operators can see tasks that are being recovered vs freshly
   queued tasks. This is critical for debugging stuck workers.
2. Deduplication safety: the recovery path can check for 'recovering' tasks
   before re-enqueuing to prevent double-enqueue race conditions.
3. Audit trail: lineage records can capture the recovering transition,
   giving a complete picture of task lifecycle including failure recovery.

State machine additions:
------------------------
  running → recovering   (lease expired, recovery initiated)
  recovering → queued    (re-enqueued for pickup by a healthy worker)
  recovering → dead_lettered  (max retries exceeded during recovery)

The 'recovering' state is transient — tasks should not remain in this state
for more than one recovery cycle (typically < 60 seconds).

Migration strategy:
-------------------
PostgreSQL does not support ALTER TYPE ... ADD VALUE inside a transaction
block in older versions. We use a conditional approach:
1. Drop the existing check constraint on execution_tasks.status
2. Add 'recovering' to the allowed values
3. Recreate the check constraint with the new value set

This is safe because:
- The constraint is advisory (enforced at app layer by StateMachine)
- No existing rows have status='recovering' before this migration
- The window between constraint drop and recreate is within the same
  migration transaction, so concurrent writes see a consistent state
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0004"
down_revision: str = "0003"
branch_labels = None
depends_on = None

# The complete set of valid task states after this migration
_TASK_STATES_V2: tuple[str, ...] = (
    "planned",
    "queued",
    "claimed",
    "running",
    "recovering",   # NEW
    "blocked",
    "completed",
    "failed",
    "dead_lettered",
    "cancelled",
)

_TASK_STATES_V1: tuple[str, ...] = (
    "planned",
    "queued",
    "claimed",
    "running",
    "blocked",
    "completed",
    "failed",
    "dead_lettered",
    "cancelled",
)

_CONSTRAINT_NAME = "ck_execution_tasks_status"
_TABLE_NAME = "execution_tasks"


def _make_check_values(states: tuple[str, ...]) -> str:
    """Build the SQL IN(...) value list for the check constraint."""
    quoted = ", ".join(f"'{s}'" for s in states)
    return f"status IN ({quoted})"


def upgrade() -> None:
    """Add 'recovering' to the execution_tasks status check constraint."""
    conn = op.get_bind()

    # Step 1: Drop the existing check constraint
    # Use IF EXISTS to be idempotent in case of partial migration reruns
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"
        )
    )

    # Step 2: Recreate with the new state set
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"CHECK ({_make_check_values(_TASK_STATES_V2)})"
        )
    )

    # Step 3: Add an index on (tenant_id, status) for the recovery query
    # RuntimeMaintainer queries: WHERE status = 'running' AND lease expired
    # This index also accelerates the new: WHERE status = 'recovering'
    op.create_index(
        "ix_execution_tasks_tenant_status",
        _TABLE_NAME,
        ["tenant_id", "status"],
        unique=False,
        postgresql_where=sa.text("status IN ('running', 'recovering', 'queued', 'claimed')"),
    )


def downgrade() -> None:
    """Remove 'recovering' from the check constraint and drop the new index."""
    conn = op.get_bind()

    # Refuse downgrade if any tasks are currently in 'recovering' state
    result = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE_NAME} WHERE status = 'recovering'")
    ).scalar()
    if result and result > 0:
        raise RuntimeError(
            f"Cannot downgrade: {result} task(s) are in 'recovering' state. "
            "Resolve these tasks before rolling back this migration."
        )

    # Drop the new index
    op.drop_index("ix_execution_tasks_tenant_status", table_name=_TABLE_NAME)

    # Restore the original check constraint
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"
        )
    )
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"CHECK ({_make_check_values(_TASK_STATES_V1)})"
        )
    )
