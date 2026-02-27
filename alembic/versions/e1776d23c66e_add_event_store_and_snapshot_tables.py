"""add_event_store_and_snapshot_tables

Revision ID: e1776d23c66e
Revises: 5a5865f18057
Create Date: 2026-02-27 16:51:29.499273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1776d23c66e'
down_revision: Union[str, None] = '5a5865f18057'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # event_store — immutable, append-only domain event log
    # =========================================================================
    op.create_table(
        'event_store',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.String(36), nullable=False, unique=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('aggregate_id', sa.String(36), nullable=False),
        sa.Column('aggregate_type', sa.String(50), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('metadata', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_es_event_id',         'event_store', ['event_id'],         unique=True)
    op.create_index('idx_es_aggregate',         'event_store', ['aggregate_id', 'version'])
    op.create_index('idx_es_event_type',        'event_store', ['event_type'])
    op.create_index('idx_es_aggregate_type_ts', 'event_store', ['aggregate_type', 'timestamp'])
    op.create_index('idx_es_timestamp',         'event_store', ['timestamp'])

    # =========================================================================
    # snapshot_store — aggregate state snapshots to speed up replay
    # =========================================================================
    op.create_table(
        'snapshot_store',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('aggregate_id', sa.String(36), nullable=False),
        sa.Column('aggregate_type', sa.String(50), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_ss_aggregate_id',      'snapshot_store', ['aggregate_id'])
    op.create_index('idx_ss_aggregate_version', 'snapshot_store', ['aggregate_id', 'version'])
    op.create_index('idx_ss_timestamp',         'snapshot_store', ['timestamp'])


def downgrade() -> None:
    op.drop_index('idx_ss_timestamp',         table_name='snapshot_store')
    op.drop_index('idx_ss_aggregate_version', table_name='snapshot_store')
    op.drop_index('idx_ss_aggregate_id',      table_name='snapshot_store')
    op.drop_table('snapshot_store')

    op.drop_index('idx_es_timestamp',         table_name='event_store')
    op.drop_index('idx_es_aggregate_type_ts', table_name='event_store')
    op.drop_index('idx_es_event_type',        table_name='event_store')
    op.drop_index('idx_es_aggregate',         table_name='event_store')
    op.drop_index('idx_es_event_id',          table_name='event_store')
    op.drop_table('event_store')
