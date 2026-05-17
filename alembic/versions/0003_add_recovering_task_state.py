"""Add recovering task state.

Revision ID: 0003_add_recovering_task_state
Revises: 0002_add_api_key_records
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_add_recovering_task_state"
down_revision = "0002_add_api_key_records"
branch_labels = None
depends_on = None

_TABLE_NAME = "execution_tasks"
_CONSTRAINT_NAME = "ck_execution_tasks_status"

_TASK_STATES_WITH_RECOVERING: tuple[str, ...] = (
    "planned",
    "queued",
    "claimed",
    "running",
    "recovering",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "dead_lettered",
)

_TASK_STATES_WITHOUT_RECOVERING: tuple[str, ...] = (
    "planned",
    "queued",
    "claimed",
    "running",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "dead_lettered",
)


def _state_check(states: tuple[str, ...]) -> str:
    values = ", ".join(f"'{state}'" for state in states)
    return f"status IN ({values})"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(f"ALTER TABLE {_TABLE_NAME} DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"))
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"CHECK ({_state_check(_TASK_STATES_WITH_RECOVERING)})"
        )
    )

    op.create_index(
        "ix_execution_tasks_tenant_status_recovery",
        _TABLE_NAME,
        ["tenant_id", "status"],
        unique=False,
        postgresql_where=sa.text("status IN ('running', 'recovering', 'queued', 'claimed')"),
    )


def downgrade() -> None:
    conn = op.get_bind()

    recovering_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE_NAME} WHERE status = 'recovering'")
    ).scalar()

    if recovering_count:
        raise RuntimeError("Cannot downgrade while execution_tasks rows are in recovering state.")

    op.drop_index("ix_execution_tasks_tenant_status_recovery", table_name=_TABLE_NAME)

    conn.execute(sa.text(f"ALTER TABLE {_TABLE_NAME} DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"))
    conn.execute(
        sa.text(
            f"ALTER TABLE {_TABLE_NAME} "
            f"ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"CHECK ({_state_check(_TASK_STATES_WITHOUT_RECOVERING)})"
        )
    )
