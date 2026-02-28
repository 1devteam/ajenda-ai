"""
Governance System Database Models
SQLAlchemy ORM models for AI governance persistence

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
    Enum as SQLEnum,
    Index,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from backend.database.base import Base


# Enums for type safety
class AssetType(str, enum.Enum):
    """Asset types in governance system"""

    AGENT = "agent"
    TOOL = "tool"
    MODEL = "model"
    VECTOR_DB = "vector_db"
    DATASET = "dataset"
    WORKFLOW = "workflow"


class AssetStatus(str, enum.Enum):
    """Asset lifecycle status"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"
    UNDER_REVIEW = "under_review"


class RiskTier(str, enum.Enum):
    """EU AI Act risk tiers"""

    UNACCEPTABLE = "unacceptable"
    HIGH = "high"
    LIMITED = "limited"
    MINIMAL = "minimal"


class AuthorityLevel(str, enum.Enum):
    """User authority levels for governance"""

    GUEST = "guest"
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"
    COMPLIANCE_OFFICER = "compliance_officer"


class ApprovalStatus(str, enum.Enum):
    """Approval workflow status"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"


class PolicyStatus(str, enum.Enum):
    """Policy lifecycle status"""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ComplianceStatus(str, enum.Enum):
    """Compliance check results"""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"
    EXEMPTED = "exempted"


# Models
class GovernanceAsset(Base):
    """
    Asset Registry - Tracks all AI assets under governance
    Replaces in-memory asset_registry.py storage
    """

    __tablename__ = "governance_assets"
    __table_args__ = (
        # Most common list query: tenant + status + created_at (paginated)
        Index(
            "ix_governance_assets_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        # Risk dashboard: tenant + risk_tier + risk_score (sorted)
        Index(
            "ix_governance_assets_tenant_risk_tier_score",
            "tenant_id",
            "risk_tier",
            "risk_score",
        ),
        # Compliance view: tenant + compliance_status + updated_at
        Index(
            "ix_governance_assets_tenant_compliance_updated",
            "tenant_id",
            "compliance_status",
            "updated_at",
        ),
        # Owner lookup: tenant + owner_id + status
        Index(
            "ix_governance_assets_tenant_owner_status",
            "tenant_id",
            "owner_id",
            "status",
        ),
    )

    # Primary identification
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    asset_type = Column(SQLEnum(AssetType), nullable=False, index=True)
    status = Column(
        SQLEnum(AssetStatus), nullable=False, index=True, default=AssetStatus.ACTIVE
    )

    # Ownership & tenant
    owner_id = Column(String(50), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)

    # Metadata
    description = Column(Text, nullable=True)
    version = Column(String(50), nullable=True)
    tags = Column(JSON, default=list, nullable=False)  # Contextual tags
    asset_metadata = Column(JSON, default=dict, nullable=False)  # Flexible metadata

    # Dependencies
    dependencies = Column(JSON, default=list, nullable=False)  # List of asset IDs

    # Risk & compliance
    risk_tier = Column(SQLEnum(RiskTier), nullable=True, index=True)
    risk_score = Column(Float, nullable=True)
    compliance_status = Column(SQLEnum(ComplianceStatus), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_assessed_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant", backref="governance_assets")
    lineage_events = relationship(
        "GovernanceLineageEvent", back_populates="asset", cascade="all, delete-orphan"
    )
    risk_scores = relationship(
        "GovernanceRiskScore", back_populates="asset", cascade="all, delete-orphan"
    )
    audit_events = relationship(
        "GovernanceAuditEvent", back_populates="asset", cascade="all, delete-orphan"
    )
    approvals = relationship(
        "GovernanceApproval", back_populates="asset", cascade="all, delete-orphan"
    )


class GovernanceLineageEvent(Base):
    """
    Lineage Tracking - Tracks asset lifecycle events
    Replaces in-memory lineage_tracker.py storage
    """

    __tablename__ = "governance_lineage_events"
    __table_args__ = (
        # Most common: asset history ordered by time
        Index("ix_governance_lineage_asset_timestamp", "asset_id", "timestamp"),
        # Event type filter per asset
        Index(
            "ix_governance_lineage_asset_event_type",
            "asset_id",
            "event_type",
            "timestamp",
        ),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=False, index=True
    )
    event_type = Column(
        String(50), nullable=False, index=True
    )  # created, updated, deployed, etc.
    event_data = Column(JSON, default=dict, nullable=False)
    actor_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    asset = relationship("GovernanceAsset", back_populates="lineage_events")


class GovernanceRiskScore(Base):
    """
    Risk Scoring - Historical risk assessments
    Replaces in-memory risk_scoring.py storage
    """

    __tablename__ = "governance_risk_scores"
    __table_args__ = (
        # Trend queries: asset history ordered by time
        Index(
            "ix_governance_risk_scores_asset_calculated", "asset_id", "calculated_at"
        ),
        # Tier filter: asset + tier + calculated_at
        Index(
            "ix_governance_risk_scores_asset_tier_calculated",
            "asset_id",
            "tier",
            "calculated_at",
        ),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=False, index=True
    )

    # Risk assessment
    tier = Column(SQLEnum(RiskTier), nullable=False, index=True)
    score = Column(Float, nullable=False)
    factors = Column(JSON, default=dict, nullable=False)  # Risk factors breakdown

    # Metadata
    calculated_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    calculated_by = Column(String(50), nullable=False)  # User or system
    method = Column(String(50), nullable=False)  # scoring_method used

    # Relationships
    asset = relationship("GovernanceAsset", back_populates="risk_scores")


class GovernancePolicy(Base):
    """
    Policy Definitions - Governance policies
    Replaces in-memory policy_engine.py storage
    """

    __tablename__ = "governance_policies"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Policy configuration
    status = Column(
        SQLEnum(PolicyStatus), nullable=False, index=True, default=PolicyStatus.DRAFT
    )
    priority = Column(
        Integer, nullable=False, default=0, index=True
    )  # Higher = more important
    applies_to = Column(
        JSON, default=list, nullable=False
    )  # List of asset types or IDs

    # Policy rules
    rules = Column(JSON, nullable=False)  # Policy rule definitions
    conditions = Column(JSON, default=dict, nullable=False)  # Evaluation conditions
    actions = Column(JSON, default=dict, nullable=False)  # Actions on violation

    # Metadata
    created_by = Column(String(50), nullable=False)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    tenant = relationship("Tenant", backref="governance_policies")
    evaluations = relationship(
        "GovernancePolicyEvaluation",
        back_populates="policy",
        cascade="all, delete-orphan",
    )


class GovernancePolicyEvaluation(Base):
    """
    Policy Evaluations - Cached policy evaluation results
    Replaces in-memory policy evaluation cache
    """

    __tablename__ = "governance_policy_evaluations"

    id = Column(String(50), primary_key=True, index=True)
    policy_id = Column(
        String(50), ForeignKey("governance_policies.id"), nullable=False, index=True
    )
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=False, index=True
    )

    # Evaluation result
    result = Column(String(20), nullable=False)  # allow, deny, warn
    violations = Column(JSON, default=list, nullable=False)
    recommendations = Column(JSON, default=list, nullable=False)

    # Metadata
    evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    context = Column(JSON, default=dict, nullable=False)

    # Relationships
    policy = relationship("GovernancePolicy", back_populates="evaluations")


class GovernanceAuditEvent(Base):
    """
    Audit Events - Comprehensive audit trail
    Replaces in-memory audit_monitor.py storage
    """

    __tablename__ = "governance_audit_events"
    __table_args__ = (
        # Most common: tenant audit log ordered by time
        Index("ix_governance_audit_tenant_timestamp", "tenant_id", "timestamp"),
        # Asset-specific audit trail
        Index("ix_governance_audit_asset_timestamp", "asset_id", "timestamp"),
        # Severity filter: tenant + severity + timestamp
        Index(
            "ix_governance_audit_tenant_severity_timestamp",
            "tenant_id",
            "severity",
            "timestamp",
        ),
        # Actor lookup: tenant + actor_id + timestamp
        Index(
            "ix_governance_audit_tenant_actor_timestamp",
            "tenant_id",
            "actor_id",
            "timestamp",
        ),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=True, index=True
    )

    # Event details
    event_type = Column(String(50), nullable=False, index=True)
    event_category = Column(
        String(50), nullable=False, index=True
    )  # access, modification, compliance, etc.
    severity = Column(
        String(20), nullable=False, index=True
    )  # info, warning, error, critical

    # Actor information
    actor_id = Column(String(50), nullable=False, index=True)
    actor_type = Column(String(50), nullable=False)  # user, agent, system

    # Event data
    event_data = Column(JSON, default=dict, nullable=False)
    outcome = Column(String(20), nullable=False)  # success, failure, blocked

    # Metadata
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)

    # Relationships
    tenant = relationship("Tenant", backref="governance_audit_events")
    asset = relationship("GovernanceAsset", back_populates="audit_events")


class GovernanceApproval(Base):
    """
    Approval Workflows - Multi-stage approval tracking
    Replaces in-memory approval_workflow.py storage
    """

    __tablename__ = "governance_approvals"
    __table_args__ = (
        # Pending approvals dashboard: tenant + status + requested_at
        Index(
            "ix_governance_approvals_tenant_status_requested",
            "tenant_id",
            "status",
            "requested_at",
        ),
        # Asset approval history
        Index("ix_governance_approvals_asset_status", "asset_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=False, index=True
    )

    # Request details
    request_type = Column(
        String(50), nullable=False
    )  # deployment, modification, access, etc.
    requested_by = Column(String(50), nullable=False, index=True)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Approval requirements
    required_authority = Column(SQLEnum(AuthorityLevel), nullable=False, index=True)
    status = Column(
        SQLEnum(ApprovalStatus),
        nullable=False,
        index=True,
        default=ApprovalStatus.PENDING,
    )

    # Approval chain
    approvers = Column(JSON, default=list, nullable=False)  # List of approver IDs
    approved_by = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Context
    context = Column(JSON, default=dict, nullable=False)
    risk_tier = Column(SQLEnum(RiskTier), nullable=False)

    # Expiration
    expires_at = Column(DateTime, nullable=True)

    # Metadata
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)

    # Relationships
    tenant = relationship("Tenant", backref="governance_approvals")
    asset = relationship("GovernanceAsset", back_populates="approvals")


class GovernanceComplianceFinding(Base):
    """
    Compliance Findings - Results of compliance checks
    Replaces in-memory compliance_checker.py storage
    """

    __tablename__ = "governance_compliance_findings"
    __table_args__ = (
        # Compliance dashboard: tenant + status + checked_at
        Index(
            "ix_governance_compliance_tenant_status_checked",
            "tenant_id",
            "status",
            "checked_at",
        ),
        # Asset compliance history
        Index("ix_governance_compliance_asset_checked", "asset_id", "checked_at"),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(
        String(50), ForeignKey("governance_assets.id"), nullable=False, index=True
    )

    # Finding details
    check_type = Column(
        String(50), nullable=False, index=True
    )  # policy, regulatory, security, etc.
    status = Column(SQLEnum(ComplianceStatus), nullable=False, index=True)
    severity = Column(String(20), nullable=False)  # low, medium, high, critical

    # Finding data
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    violations = Column(JSON, default=list, nullable=False)
    recommendations = Column(JSON, default=list, nullable=False)

    # Remediation
    remediation_required = Column(Boolean, default=False, nullable=False)
    remediation_deadline = Column(DateTime, nullable=True)
    remediation_status = Column(String(50), nullable=True)

    # Metadata
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    checked_by = Column(String(50), nullable=False)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)

    # Relationships
    tenant = relationship("Tenant", backref="governance_compliance_findings")


class GovernanceWebhook(Base):
    """
    Webhook Subscriptions - External system integrations
    Replaces in-memory webhook_manager.py storage
    """

    __tablename__ = "governance_webhooks"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)

    # Subscription
    event_types = Column(JSON, default=list, nullable=False)  # Events to subscribe to
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Authentication
    secret = Column(String(255), nullable=True)  # HMAC secret for verification
    headers = Column(JSON, default=dict, nullable=False)  # Custom headers

    # Retry configuration
    max_retries = Column(Integer, default=3, nullable=False)
    retry_delay_seconds = Column(Integer, default=60, nullable=False)

    # Statistics
    total_deliveries = Column(Integer, default=0, nullable=False)
    successful_deliveries = Column(Integer, default=0, nullable=False)
    failed_deliveries = Column(Integer, default=0, nullable=False)
    last_delivery_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)

    # Metadata
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref="governance_webhooks")


class GovernanceAPIKey(Base):
    """
    API Key Management - Programmatic access keys
    Replaces in-memory api_gateway.py storage
    """

    __tablename__ = "governance_api_keys"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    key_hash = Column(
        String(255), nullable=False, unique=True, index=True
    )  # Hashed key
    key_prefix = Column(String(10), nullable=False)  # First 8 chars for identification

    # Permissions
    scopes = Column(JSON, default=list, nullable=False)  # List of allowed operations
    rate_limit = Column(Integer, nullable=True)  # Custom rate limit (req/hour)

    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)

    # Usage statistics
    total_requests = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_ip = Column(String(50), nullable=True)

    # Metadata
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref="governance_api_keys")
