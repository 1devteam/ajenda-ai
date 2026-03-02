"""add_governance_tables

Revision ID: 5a5865f18057
Revises: 3d39706f076f
Create Date: 2026-02-27 06:20:04.715624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = '5a5865f18057'
down_revision: Union[str, None] = '3d39706f076f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Use postgresql.ENUM with create_type=False so SQLAlchemy does NOT attempt
# to auto-CREATE the type during op.create_table(). We create them explicitly
# via DO blocks below (idiomatic PostgreSQL 15 approach for idempotent creation).
assettype_enum = ENUM(
    'agent', 'tool', 'model', 'vector_db', 'dataset', 'workflow',
    name='assettype', create_type=False
)
assetstatus_enum = ENUM(
    'active', 'inactive', 'archived', 'suspended', 'under_review',
    name='assetstatus', create_type=False
)
risktier_enum = ENUM(
    'unacceptable', 'high', 'limited', 'minimal',
    name='risktier', create_type=False
)
authoritylevel_enum = ENUM(
    'guest', 'user', 'operator', 'admin', 'compliance_officer',
    name='authoritylevel', create_type=False
)
approvalstatus_enum = ENUM(
    'pending', 'approved', 'rejected', 'escalated', 'expired',
    name='approvalstatus', create_type=False
)
policystatus_enum = ENUM(
    'draft', 'active', 'inactive', 'archived',
    name='policystatus', create_type=False
)
compliancestatus_enum = ENUM(
    'compliant', 'non_compliant', 'needs_review', 'exempted',
    name='compliancestatus', create_type=False
)


def upgrade() -> None:
    """Create governance tables for AI governance system"""

    # Create enum types using DO blocks — idiomatic PostgreSQL 15 approach.
    # Each DO block catches duplicate_object so migration is idempotent.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE assettype AS ENUM ('agent', 'tool', 'model', 'vector_db', 'dataset', 'workflow');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE assetstatus AS ENUM ('active', 'inactive', 'archived', 'suspended', 'under_review');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE risktier AS ENUM ('unacceptable', 'high', 'limited', 'minimal');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE authoritylevel AS ENUM ('guest', 'user', 'operator', 'admin', 'compliance_officer');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE approvalstatus AS ENUM ('pending', 'approved', 'rejected', 'escalated', 'expired');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE policystatus AS ENUM ('draft', 'active', 'inactive', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE TYPE compliancestatus AS ENUM ('compliant', 'non_compliant', 'needs_review', 'exempted');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # 1. Governance Assets
    op.create_table(
        'governance_assets',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('asset_type', assettype_enum, nullable=False, index=True),
        sa.Column('status', assetstatus_enum, nullable=False, index=True),
        sa.Column('owner_id', sa.String(50), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('version', sa.String(50), nullable=True),
        sa.Column('tags', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('asset_metadata', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('dependencies', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('risk_tier', risktier_enum, nullable=True, index=True),
        sa.Column('risk_score', sa.Float, nullable=True),
        sa.Column('compliance_status', compliancestatus_enum, nullable=True, index=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('last_assessed_at', sa.DateTime, nullable=True),
    )

    # 2. Governance Lineage Events
    op.create_table(
        'governance_lineage_events',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('event_type', sa.String(50), nullable=False, index=True),
        sa.Column('event_data', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('actor_id', sa.String(50), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
    )

    # 3. Governance Risk Scores
    op.create_table(
        'governance_risk_scores',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tier', risktier_enum, nullable=False, index=True),
        sa.Column('score', sa.Float, nullable=False),
        sa.Column('factors', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('calculated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('calculated_by', sa.String(50), nullable=False),
        sa.Column('method', sa.String(50), nullable=False),
    )

    # 4. Governance Policies
    op.create_table(
        'governance_policies',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('status', policystatus_enum, nullable=False, index=True),
        sa.Column('priority', sa.Integer, nullable=False, server_default='0', index=True),
        sa.Column('applies_to', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('rules', sa.JSON, nullable=False),
        sa.Column('conditions', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('actions', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # 5. Governance Policy Evaluations
    op.create_table(
        'governance_policy_evaluations',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('policy_id', sa.String(50), sa.ForeignKey('governance_policies.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('result', sa.String(20), nullable=False),
        sa.Column('violations', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('recommendations', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('evaluated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('context', sa.JSON, nullable=False, server_default='{}'),
    )

    # 6. Governance Audit Events
    op.create_table(
        'governance_audit_events',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('event_type', sa.String(50), nullable=False, index=True),
        sa.Column('event_category', sa.String(50), nullable=False, index=True),
        sa.Column('severity', sa.String(20), nullable=False, index=True),
        sa.Column('actor_id', sa.String(50), nullable=False, index=True),
        sa.Column('actor_type', sa.String(50), nullable=False),
        sa.Column('event_data', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('outcome', sa.String(20), nullable=False),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(255), nullable=True),
    )

    # 7. Governance Approvals
    op.create_table(
        'governance_approvals',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('request_type', sa.String(50), nullable=False),
        sa.Column('requested_by', sa.String(50), nullable=False, index=True),
        sa.Column('requested_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('required_authority', authoritylevel_enum, nullable=False, index=True),
        sa.Column('status', approvalstatus_enum, nullable=False, index=True),
        sa.Column('approvers', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('approved_by', sa.String(50), nullable=True),
        sa.Column('approved_at', sa.DateTime, nullable=True),
        sa.Column('rejection_reason', sa.Text, nullable=True),
        sa.Column('context', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('risk_tier', risktier_enum, nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=True),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
    )

    # 8. Governance Compliance Findings
    op.create_table(
        'governance_compliance_findings',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('asset_id', sa.String(50), sa.ForeignKey('governance_assets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('check_type', sa.String(50), nullable=False, index=True),
        sa.Column('status', compliancestatus_enum, nullable=False, index=True),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('violations', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('recommendations', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('remediation_required', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('remediation_deadline', sa.DateTime, nullable=True),
        sa.Column('remediation_status', sa.String(50), nullable=True),
        sa.Column('checked_at', sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('checked_by', sa.String(50), nullable=False),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
    )

    # 9. Governance Webhooks
    op.create_table(
        'governance_webhooks',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('event_types', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true', index=True),
        sa.Column('secret', sa.String(255), nullable=True),
        sa.Column('headers', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('max_retries', sa.Integer, nullable=False, server_default='3'),
        sa.Column('retry_delay_seconds', sa.Integer, nullable=False, server_default='60'),
        sa.Column('total_deliveries', sa.Integer, nullable=False, server_default='0'),
        sa.Column('successful_deliveries', sa.Integer, nullable=False, server_default='0'),
        sa.Column('failed_deliveries', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_delivery_at', sa.DateTime, nullable=True),
        sa.Column('last_success_at', sa.DateTime, nullable=True),
        sa.Column('last_failure_at', sa.DateTime, nullable=True),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 10. Governance API Keys
    op.create_table(
        'governance_api_keys',
        sa.Column('id', sa.String(50), primary_key=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('key_prefix', sa.String(10), nullable=False),
        sa.Column('scopes', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('rate_limit', sa.Integer, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true', index=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
        sa.Column('total_requests', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_used_at', sa.DateTime, nullable=True),
        sa.Column('last_ip', sa.String(50), nullable=True),
        sa.Column('tenant_id', sa.String(50), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # Create composite indexes for common queries
    op.create_index('idx_assets_tenant_type_status', 'governance_assets', ['tenant_id', 'asset_type', 'status'])
    op.create_index('idx_assets_risk_tier_status', 'governance_assets', ['risk_tier', 'status'])
    op.create_index('idx_lineage_asset_timestamp', 'governance_lineage_events', ['asset_id', 'timestamp'])
    op.create_index('idx_risk_scores_asset_calculated', 'governance_risk_scores', ['asset_id', 'calculated_at'])
    op.create_index('idx_audit_tenant_timestamp', 'governance_audit_events', ['tenant_id', 'timestamp'])
    op.create_index('idx_audit_asset_event_type', 'governance_audit_events', ['asset_id', 'event_type'])
    op.create_index('idx_approvals_status_tenant', 'governance_approvals', ['status', 'tenant_id'])
    op.create_index('idx_policy_evals_asset_policy', 'governance_policy_evaluations', ['asset_id', 'policy_id'])


def downgrade() -> None:
    """Drop governance tables"""

    # Drop composite indexes first
    op.drop_index('idx_policy_evals_asset_policy', table_name='governance_policy_evaluations')
    op.drop_index('idx_approvals_status_tenant', table_name='governance_approvals')
    op.drop_index('idx_audit_asset_event_type', table_name='governance_audit_events')
    op.drop_index('idx_audit_tenant_timestamp', table_name='governance_audit_events')
    op.drop_index('idx_risk_scores_asset_calculated', table_name='governance_risk_scores')
    op.drop_index('idx_lineage_asset_timestamp', table_name='governance_lineage_events')
    op.drop_index('idx_assets_risk_tier_status', table_name='governance_assets')
    op.drop_index('idx_assets_tenant_type_status', table_name='governance_assets')

    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('governance_api_keys')
    op.drop_table('governance_webhooks')
    op.drop_table('governance_compliance_findings')
    op.drop_table('governance_approvals')
    op.drop_table('governance_audit_events')
    op.drop_table('governance_policy_evaluations')
    op.drop_table('governance_policies')
    op.drop_table('governance_risk_scores')
    op.drop_table('governance_lineage_events')
    op.drop_table('governance_assets')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS compliancestatus")
    op.execute("DROP TYPE IF EXISTS policystatus")
    op.execute("DROP TYPE IF EXISTS approvalstatus")
    op.execute("DROP TYPE IF EXISTS authoritylevel")
    op.execute("DROP TYPE IF EXISTS risktier")
    op.execute("DROP TYPE IF EXISTS assetstatus")
    op.execute("DROP TYPE IF EXISTS assettype")
