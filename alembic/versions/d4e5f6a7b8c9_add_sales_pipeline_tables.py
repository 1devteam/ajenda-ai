"""add_sales_pipeline_tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-02

Phase 5 — The Revenue Agent (v6.4)

Adds four tables that form the Sales Pipeline domain model:
  - leads         : Prospective customers discovered by the Revenue Agent
  - opportunities : Qualified leads assessed as real sales opportunities
  - proposals     : AI-generated sales proposals for each opportunity
  - deals         : Closed (won) opportunities — the revenue ground truth
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ leads
    op.create_table(
        "leads",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        # Identity
        sa.Column("company_name", sa.String(255), nullable=False, index=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True, index=True),
        sa.Column("contact_title", sa.String(255), nullable=True),
        sa.Column("contact_linkedin", sa.String(500), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        # Classification
        sa.Column("industry", sa.String(100), nullable=True, index=True),
        sa.Column("company_size", sa.String(50), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        # Qualification
        sa.Column("status", sa.String(50), nullable=False, default="new", index=True),
        sa.Column("qualification_score", sa.Float, nullable=True),
        sa.Column("qualification_notes", sa.Text, nullable=True),
        sa.Column("disqualification_reason", sa.String(255), nullable=True),
        # Research data
        sa.Column("research_data", sa.JSON, nullable=False, server_default="{}"),
        # Financials (denormalised)
        sa.Column("estimated_value", sa.Numeric(12, 2), nullable=True),
        # Notes
        sa.Column("notes", sa.Text, nullable=True),
        # Source tracking
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("qualified_at", sa.DateTime, nullable=True),
        sa.Column("converted_at", sa.DateTime, nullable=True),
    )

    # ------------------------------------------------------------ opportunities
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "lead_id",
            sa.String(50),
            sa.ForeignKey("leads.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assigned_agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        # Identity
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # Financials
        sa.Column("estimated_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("probability", sa.Float, nullable=True),
        sa.Column("expected_close_date", sa.DateTime, nullable=True),
        # Stage
        sa.Column(
            "stage",
            sa.String(50),
            nullable=False,
            server_default="discovery",
            index=True,
        ),
        # Status (pipeline status for filtering)
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="open",
            index=True,
        ),
        sa.Column("close_reason", sa.String(255), nullable=True),
        sa.Column("actual_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("closed_at", sa.DateTime, nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # --------------------------------------------------------------- proposals
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "opportunity_id",
            sa.String(50),
            sa.ForeignKey("opportunities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "generated_by_agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        # Content
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("executive_summary", sa.Text, nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("call_to_action", sa.Text, nullable=True),
        # Delivery
        sa.Column("status", sa.String(50), nullable=False, default="draft", index=True),
        sa.Column("sent_via", sa.String(50), nullable=True),
        sa.Column("sent_to_email", sa.String(255), nullable=True),
        sa.Column("sent_to_linkedin", sa.String(500), nullable=True),
        # Response tracking
        sa.Column("response_received", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("response_sentiment", sa.String(50), nullable=True),
        sa.Column("response_notes", sa.Text, nullable=True),
        # Version
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("viewed_at", sa.DateTime, nullable=True),
        sa.Column("responded_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )

    # ------------------------------------------------------------------ deals
    op.create_table(
        "deals",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "opportunity_id",
            sa.String(50),
            sa.ForeignKey("opportunities.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "lead_id",
            sa.String(50),
            sa.ForeignKey("leads.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "closed_by_agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        # Financials
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("recurring_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        # Payment
        sa.Column(
            "payment_status",
            sa.String(50),
            nullable=False,
            default="pending",
            index=True,
        ),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        # Attribution
        sa.Column("source_campaign", sa.String(255), nullable=True),
        sa.Column(
            "attributed_workforce_id",
            sa.String(50),
            sa.ForeignKey("workforces.id"),
            nullable=True,
        ),
        # Notes
        sa.Column("notes", sa.Text, nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "closed_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Composite indexes for common query patterns
    op.create_index(
        "ix_leads_tenant_status",
        "leads",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_opportunities_tenant_stage",
        "opportunities",
        ["tenant_id", "stage"],
    )
    op.create_index(
        "ix_deals_tenant_payment",
        "deals",
        ["tenant_id", "payment_status"],
    )
    op.create_index(
        "ix_deals_tenant_closed_at",
        "deals",
        ["tenant_id", "closed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deals_tenant_closed_at", table_name="deals")
    op.drop_index("ix_deals_tenant_payment", table_name="deals")
    op.drop_index("ix_opportunities_tenant_stage", table_name="opportunities")
    op.drop_index("ix_leads_tenant_status", table_name="leads")
    op.drop_table("deals")
    op.drop_table("proposals")
    op.drop_table("opportunities")
    op.drop_table("leads")
