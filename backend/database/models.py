"""
SQLAlchemy Database Models
ORM models for PostgreSQL persistence

Built with Pride for Obex Blackvault
"""

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Float,
    Integer,
    Boolean,
    ForeignKey,
    JSON,
    Text,
    Numeric,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.database.base import Base


class User(Base):
    """User model with authentication"""

    __tablename__ = "users"

    id = Column(String(50), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")


class Token(Base):
    """Access and refresh tokens"""

    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(500), unique=True, index=True, nullable=False)
    token_type = Column(String(20), nullable=False)  # 'access' or 'refresh'
    user_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User", back_populates="tokens")


class Tenant(Base):
    """Multi-tenant organization"""

    __tablename__ = "tenants"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    settings = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    users = relationship("User", back_populates="tenant")
    agents = relationship("Agent", back_populates="tenant")
    missions = relationship("Mission", back_populates="tenant")


class Agent(Base):
    """AI Agent model"""

    __tablename__ = "agents"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    temperature = Column(Float, default=0.7, nullable=False)
    system_prompt = Column(Text, nullable=True)
    capabilities = Column(JSON, default=list, nullable=False)
    config = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active = Column(DateTime, nullable=True)
    total_missions = Column(Integer, default=0, nullable=False)
    successful_missions = Column(Integer, default=0, nullable=False)
    failed_missions = Column(Integer, default=0, nullable=False)
    credit_balance = Column(Float, default=1000.0, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="agents")
    missions = relationship("Mission", back_populates="agent")


class Mission(Base):
    """Mission/Task model"""

    __tablename__ = "missions"

    id = Column(String(50), primary_key=True, index=True)
    objective = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    priority = Column(String(20), nullable=False, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    context = Column(JSON, default=dict, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    steps = Column(JSON, default=list, nullable=False)
    max_steps = Column(Integer, default=10, nullable=False)
    timeout_seconds = Column(Integer, default=300, nullable=False)
    execution_time = Column(Float, nullable=True)
    tokens_used = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    budget = Column(Float, nullable=True)  # Optional credit budget cap for this mission
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="missions")
    agent = relationship("Agent", back_populates="missions")


class ScheduledJob(Base):
    """
    Scheduled job model for recurring and one-off agent missions.

    Supports two trigger types:
      - ``cron``:     Standard cron expression (e.g. ``"0 9 * * 1-5"`` for weekdays at 9 AM).
      - ``interval``: Fixed interval in seconds (e.g. ``3600`` for every hour).

    The ``mission_payload`` JSON field contains the full mission specification
    that will be submitted to the MissionExecutor when the job fires.
    """

    __tablename__ = "scheduled_jobs"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Identity
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)

    # Trigger configuration
    trigger_type = Column(String(20), nullable=False)  # 'cron' | 'interval'
    cron_expression = Column(String(100), nullable=True)   # e.g. "0 9 * * 1-5"
    interval_seconds = Column(Integer, nullable=True)      # e.g. 3600

    # Mission payload — submitted to MissionExecutor on each trigger
    mission_payload = Column(JSON, nullable=False)

    # State
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    max_runs = Column(Integer, nullable=True)   # None = unlimited
    run_count = Column(Integer, default=0, nullable=False)

    # Execution tracking
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(50), nullable=True)   # 'success' | 'failed' | 'running'
    last_run_mission_id = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    agent = relationship("Agent")
    creator = relationship("User", foreign_keys=[created_by])


class ExternalAPIKey(Base):
    """
    Encrypted external API key storage.

    Keys are encrypted with AES-256-GCM before storage.  The encryption key
    is derived from the application SECRET_KEY and is never stored in the DB.
    Only the ciphertext, nonce, and tag are persisted.

    Supported services: ``reddit``, ``twitter``, ``linkedin``, ``openai``, etc.
    """

    __tablename__ = "external_api_keys"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)

    # Key identity
    service = Column(String(100), nullable=False, index=True)   # e.g. 'reddit'
    key_name = Column(String(255), nullable=False)               # e.g. 'production'

    # Encrypted key material (AES-256-GCM)
    encrypted_value = Column(Text, nullable=False)   # base64-encoded ciphertext+tag
    nonce = Column(String(64), nullable=False)        # base64-encoded 12-byte nonce

    # Optional metadata (non-sensitive)
    # Note: 'metadata' is reserved by SQLAlchemy Declarative API — use 'key_metadata'
    key_metadata = Column("metadata", JSON, default=dict, nullable=False)

    # State
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    creator = relationship("User", foreign_keys=[created_by])


class Workforce(Base):
    """
    Workforce configuration — a named team of agents with assigned roles.

    A Workforce is a persistent configuration that can be run multiple times.
    Each run creates a WorkforceRun (tracked in-memory by WorkforceCoordinator
    and persisted via EventStore events).

    The ``roles`` JSON field defines which AgentRole values are active in this
    workforce and maps each role to an optional agent_id override.
    """

    __tablename__ = "workforces"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Identity
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)

    # Configuration
    # e.g. [{"role": "researcher"}, {"role": "analyst"}, {"role": "writer"}]
    roles = Column(JSON, nullable=False, default=list)

    # Pipeline type: "sequential" | "parallel" | "mixed"
    pipeline_type = Column(String(20), nullable=False, default="sequential")

    # Optional default budget per run (credits)
    default_budget = Column(Float, nullable=True)

    # State
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    total_runs = Column(Integer, default=0, nullable=False)
    successful_runs = Column(Integer, default=0, nullable=False)
    failed_runs = Column(Integer, default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_run_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    creator = relationship("User", foreign_keys=[created_by])
    members = relationship(
        "WorkforceMember", back_populates="workforce", cascade="all, delete-orphan"
    )


class WorkforceMember(Base):
    """
    A single agent assigned to a specific role within a Workforce.

    Multiple members can share the same role (e.g. two researchers).
    The ``priority`` field determines which member is selected first when
    multiple members share a role.
    """

    __tablename__ = "workforce_members"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Foreign keys
    workforce_id = Column(
        String(50), ForeignKey("workforces.id"), nullable=False, index=True
    )
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)

    # Role assignment
    role = Column(String(50), nullable=False, index=True)   # AgentRole value

    # Selection priority (lower = higher priority)
    priority = Column(Integer, default=0, nullable=False)

    # State
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    workforce = relationship("Workforce", back_populates="members")
    agent = relationship("Agent")


# ============================================================================
# PHASE 5: SALES PIPELINE DOMAIN MODELS
# ============================================================================


class Lead(Base):
    """
    A prospective customer identified by the Revenue Agent.

    Leads are discovered via the LeadGenerationWorkflow (web search + browser
    automation) and qualify into Opportunities when they meet scoring criteria.

    Lifecycle: NEW → RESEARCHED → QUALIFIED → CONVERTED | DISQUALIFIED
    """

    __tablename__ = "leads"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)
    assigned_agent_id = Column(String(50), ForeignKey("agents.id"), nullable=True, index=True)

    # Identity
    company_name = Column(String(255), nullable=False, index=True)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True, index=True)
    contact_title = Column(String(255), nullable=True)
    contact_linkedin = Column(String(500), nullable=True)   # LinkedIn profile URL of contact
    website = Column(String(500), nullable=True)
    linkedin_url = Column(String(500), nullable=True)

    # Classification
    industry = Column(String(100), nullable=True, index=True)
    company_size = Column(String(50), nullable=True)   # 'startup' | 'smb' | 'mid-market' | 'enterprise'
    location = Column(String(255), nullable=True)

    # Qualification
    status = Column(String(50), nullable=False, default="new", index=True)
    # new | researched | qualified | converted | disqualified
    qualification_score = Column(Float, nullable=True)   # 0.0–1.0
    qualification_notes = Column(Text, nullable=True)
    disqualification_reason = Column(String(255), nullable=True)

    # Research data (raw output from Researcher agent)
    research_data = Column(JSON, default=dict, nullable=False)

    # Financials (denormalised from Opportunity for quick access)
    estimated_value = Column(Numeric(12, 2), nullable=True)   # USD — set during qualification

    # Notes
    notes = Column(Text, nullable=True)

    # Source tracking
    source = Column(String(100), nullable=True)   # 'web_search' | 'linkedin' | 'manual' | 'referral'
    source_url = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    qualified_at = Column(DateTime, nullable=True)
    converted_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    creator = relationship("User", foreign_keys=[created_by])
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    opportunities = relationship("Opportunity", back_populates="lead", cascade="all, delete-orphan")


class Opportunity(Base):
    """
    A qualified lead that has been assessed as a real sales opportunity.

    Opportunities track the deal value, probability, and stage through the
    sales funnel. Each Opportunity can have one active Proposal.

    Lifecycle: DISCOVERY → PROPOSAL → NEGOTIATION → CLOSED_WON | CLOSED_LOST
    """

    __tablename__ = "opportunities"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    lead_id = Column(String(50), ForeignKey("leads.id"), nullable=False, index=True)
    assigned_agent_id = Column(String(50), ForeignKey("agents.id"), nullable=True, index=True)

    # Identity
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Financials
    estimated_value = Column(Numeric(12, 2), nullable=True)   # USD
    probability = Column(Float, nullable=True)                  # 0.0–1.0
    expected_close_date = Column(DateTime, nullable=True)

    # Stage (detailed funnel position)
    stage = Column(String(50), nullable=False, default="discovery", index=True)
    # discovery | proposal | negotiation | closed_won | closed_lost

    # Status (pipeline status for filtering/dashboard)
    status = Column(String(50), nullable=False, default="open", index=True)
    # open | proposal_sent | negotiating | closed_won | closed_lost

    # Close tracking
    close_reason = Column(String(255), nullable=True)
    actual_value = Column(Numeric(12, 2), nullable=True)   # Actual closed value (USD)
    closed_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    tenant = relationship("Tenant")
    lead = relationship("Lead", back_populates="opportunities")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    proposals = relationship("Proposal", back_populates="opportunity", cascade="all, delete-orphan")
    deal = relationship("Deal", back_populates="opportunity", uselist=False)


class Proposal(Base):
    """
    An AI-generated sales proposal for an Opportunity.

    Proposals are generated by the Writer agent using the research data from
    the Lead and the qualification analysis from the Analyst agent.

    Lifecycle: DRAFT → SENT → VIEWED → ACCEPTED | REJECTED | EXPIRED
    """

    __tablename__ = "proposals"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    opportunity_id = Column(String(50), ForeignKey("opportunities.id"), nullable=False, index=True)
    generated_by_agent_id = Column(String(50), ForeignKey("agents.id"), nullable=True)

    # Content
    title = Column(String(255), nullable=False)
    executive_summary = Column(Text, nullable=True)
    body = Column(Text, nullable=False)   # Full proposal markdown
    call_to_action = Column(Text, nullable=True)

    # Delivery
    status = Column(String(50), nullable=False, default="draft", index=True)
    # draft | sent | viewed | accepted | rejected | expired
    sent_via = Column(String(50), nullable=True)   # 'email' | 'linkedin' | 'twitter' | 'manual'
    sent_to_email = Column(String(255), nullable=True)
    sent_to_linkedin = Column(String(500), nullable=True)

    # Response tracking
    response_received = Column(Boolean, default=False, nullable=False)
    response_sentiment = Column(String(50), nullable=True)   # 'positive' | 'neutral' | 'negative'
    response_notes = Column(Text, nullable=True)

    # Version tracking
    version = Column(Integer, default=1, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    sent_at = Column(DateTime, nullable=True)
    viewed_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    opportunity = relationship("Opportunity", back_populates="proposals")
    generator = relationship("Agent", foreign_keys=[generated_by_agent_id])


class Deal(Base):
    """
    A closed (won) Opportunity — the revenue record.

    Deals are created when an Opportunity moves to ``closed_won``.
    They track the actual revenue, payment status, and any recurring value.

    This is the financial ground truth for the revenue dashboard.
    """

    __tablename__ = "deals"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    opportunity_id = Column(String(50), ForeignKey("opportunities.id"), nullable=False, unique=True)
    lead_id = Column(String(50), ForeignKey("leads.id"), nullable=True, index=True)   # Denormalised for fast lookup
    closed_by_agent_id = Column(String(50), ForeignKey("agents.id"), nullable=True)

    # Financials
    value = Column(Numeric(12, 2), nullable=False)          # One-time or first payment (USD)
    recurring_value = Column(Numeric(12, 2), nullable=True)  # Monthly recurring (USD)
    currency = Column(String(10), nullable=False, default="USD")

    # Payment
    payment_status = Column(String(50), nullable=False, default="pending", index=True)
    # pending | invoiced | paid | overdue | cancelled
    invoice_number = Column(String(100), nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Attribution
    source_campaign = Column(String(255), nullable=True)   # Which campaign generated this deal
    attributed_workforce_id = Column(String(50), ForeignKey("workforces.id"), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    closed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    opportunity = relationship("Opportunity", back_populates="deal")
    closed_by = relationship("Agent", foreign_keys=[closed_by_agent_id])
    attributed_workforce = relationship("Workforce", foreign_keys=[attributed_workforce_id])
