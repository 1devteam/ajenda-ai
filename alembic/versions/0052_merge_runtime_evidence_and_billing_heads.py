"""Merge the runtime-evidence and billing migration branches.

Both branches are already valid deployed histories.  This no-op merge keeps
their schema changes intact and restores a single Alembic upgrade head.
"""

from __future__ import annotations

from alembic import op  # noqa: F401

revision = "0052_runtime_evidence_billing_merge"
down_revision = ("0050_runtime_evidence_ckpts", "0051_billing_meter_dispatches")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
