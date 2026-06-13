"""Expand capability adapter side-effect classifications.

Revision ID: 0020a_adapter_side_effects
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020a_adapter_side_effects"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_capability_adapters_side_effect_classification"
TABLE_NAME = "capability_adapters"
OLD_SIDE_EFFECT_CLASSIFICATIONS = (
    "none",
    "read_only",
    "idempotent_write",
    "non_idempotent_write",
    "external_side_effect",
)
NEW_SIDE_EFFECT_CLASSIFICATIONS = (
    "none",
    "read_only",
    "idempotent_write",
    "non_idempotent_write",
    "external_read",
    "external_write",
    "external_send",
    "external_publish",
    "external_side_effect",
)


def _classification_check(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"side_effect_classification IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        _classification_check(NEW_SIDE_EFFECT_CLASSIFICATIONS),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE capability_adapters
            SET side_effect_classification = CASE
                WHEN side_effect_classification = 'external_read' THEN 'read_only'
                WHEN side_effect_classification IN ('external_write', 'external_send', 'external_publish')
                    THEN 'external_side_effect'
                ELSE side_effect_classification
            END
            WHERE side_effect_classification IN (
                'external_read', 'external_write', 'external_send', 'external_publish'
            )
            """
        )
    )
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        _classification_check(OLD_SIDE_EFFECT_CLASSIFICATIONS),
    )
