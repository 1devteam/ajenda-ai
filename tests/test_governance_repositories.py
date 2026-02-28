"""
Governance Repository Tests
Test database repositories for governance system

Built with Pride for Obex Blackvault
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.base import Base
from backend.database.governance_models import (
    GovernanceAsset,
    AssetType,
    AssetStatus,
    RiskTier,
    ComplianceStatus,
    AuthorityLevel,
    ApprovalStatus,
    PolicyStatus
)
from backend.database.repositories import (

    AssetRepository,
    LineageRepository,
    PolicyRepository,
    PolicyEvaluationRepository,
    AuditRepository,
    ApprovalRepository
)
pytestmark = pytest.mark.unit


# Test database setup
@pytest.fixture(scope="function")
def db_session():
    """Create test database session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(engine)


# Asset Repository Tests

def test_asset_repository_create(db_session):
    """Test creating asset"""
    repo = AssetRepository(db_session)
    
    asset = repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
        description="Test description",
        tags=["test", "agent"],
        asset_metadata={"key": "value"}
    )
    
    assert asset.id == "asset_1"
    assert asset.name == "Test Agent"
    assert asset.asset_type == AssetType.AGENT
    assert asset.status == AssetStatus.ACTIVE
    assert "test" in asset.tags


def test_asset_repository_get(db_session):
    """Test getting asset by ID"""
    repo = AssetRepository(db_session)
    
    repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    asset = repo.get("asset_1")
    assert asset is not None
    assert asset.id == "asset_1"
    
    missing = repo.get("missing")
    assert missing is None


def test_asset_repository_get_by_tenant(db_session):
    """Test getting assets by tenant"""
    repo = AssetRepository(db_session)
    
    repo.create_asset(
        id="asset_1",
        name="Agent 1",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    repo.create_asset(
        id="asset_2",
        name="Agent 2",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    repo.create_asset(
        id="asset_3",
        name="Agent 3",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_2"
    )
    
    tenant1_assets = repo.get_by_tenant("tenant_1")
    assert len(tenant1_assets) == 2
    
    tenant2_assets = repo.get_by_tenant("tenant_2")
    assert len(tenant2_assets) == 1


def test_asset_repository_update_risk(db_session):
    """Test updating asset risk assessment"""
    repo = AssetRepository(db_session)
    
    asset = repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    assert asset.risk_tier is None
    
    updated = repo.update_risk_assessment(
        "asset_1",
        RiskTier.HIGH,
        0.85
    )
    
    assert updated.risk_tier == RiskTier.HIGH
    assert updated.risk_score == 0.85
    assert updated.last_assessed_at is not None


def test_asset_repository_tags(db_session):
    """Test asset tag operations"""
    repo = AssetRepository(db_session)
    
    asset = repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
        tags=["initial"]
    )
    
    # Add tag
    asset = repo.add_tag("asset_1", "new_tag")
    assert "new_tag" in asset.tags
    
    # Remove tag
    asset = repo.remove_tag("asset_1", "initial")
    assert "initial" not in asset.tags


def test_asset_repository_statistics(db_session):
    """Test asset statistics"""
    repo = AssetRepository(db_session)
    
    repo.create_asset(
        id="asset_1",
        name="Agent 1",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
        risk_tier=RiskTier.HIGH
    )
    
    repo.create_asset(
        id="asset_2",
        name="Tool 1",
        asset_type=AssetType.TOOL,
        owner_id="user_1",
        tenant_id="tenant_1",
        risk_tier=RiskTier.MINIMAL
    )
    
    stats = repo.get_statistics("tenant_1")
    
    assert stats["total"] == 2
    assert stats["by_type"][AssetType.AGENT.value] == 1
    assert stats["by_type"][AssetType.TOOL.value] == 1
    assert stats["by_risk"][RiskTier.HIGH.value] == 1


# Lineage Repository Tests

def test_lineage_repository_create(db_session):
    """Test creating lineage event"""
    asset_repo = AssetRepository(db_session)
    lineage_repo = LineageRepository(db_session)
    
    # Create asset first
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    event = lineage_repo.create_event(
        id="event_1",
        asset_id="asset_1",
        event_type="created",
        actor_id="user_1",
        event_data={"source": "api"}
    )
    
    assert event.id == "event_1"
    assert event.asset_id == "asset_1"
    assert event.event_type == "created"


def test_lineage_repository_get_history(db_session):
    """Test getting asset history"""
    asset_repo = AssetRepository(db_session)
    lineage_repo = LineageRepository(db_session)
    
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    lineage_repo.create_event(
        id="event_1",
        asset_id="asset_1",
        event_type="created",
        actor_id="user_1"
    )
    
    lineage_repo.create_event(
        id="event_2",
        asset_id="asset_1",
        event_type="updated",
        actor_id="user_1"
    )
    
    history = lineage_repo.get_asset_history("asset_1")
    assert len(history) == 2


# Policy Repository Tests

def test_policy_repository_create(db_session):
    """Test creating policy"""
    repo = PolicyRepository(db_session)
    
    policy = repo.create_policy(
        id="policy_1",
        name="PII Protection",
        tenant_id="tenant_1",
        created_by="user_1",
        rules={"deny_pii": True},
        priority=10
    )
    
    assert policy.id == "policy_1"
    assert policy.name == "PII Protection"
    assert policy.status == PolicyStatus.DRAFT
    assert policy.priority == 10


def test_policy_repository_activate(db_session):
    """Test activating policy"""
    repo = PolicyRepository(db_session)
    
    policy = repo.create_policy(
        id="policy_1",
        name="Test Policy",
        tenant_id="tenant_1",
        created_by="user_1",
        rules={}
    )
    
    assert policy.status == PolicyStatus.DRAFT
    
    activated = repo.activate_policy("policy_1")
    assert activated.status == PolicyStatus.ACTIVE


def test_policy_repository_get_active(db_session):
    """Test getting active policies"""
    repo = PolicyRepository(db_session)
    
    repo.create_policy(
        id="policy_1",
        name="Active Policy",
        tenant_id="tenant_1",
        created_by="user_1",
        rules={},
        status=PolicyStatus.ACTIVE
    )
    
    repo.create_policy(
        id="policy_2",
        name="Draft Policy",
        tenant_id="tenant_1",
        created_by="user_1",
        rules={},
        status=PolicyStatus.DRAFT
    )
    
    active = repo.get_active_policies("tenant_1")
    assert len(active) == 1
    assert active[0].id == "policy_1"


# Audit Repository Tests

def test_audit_repository_create(db_session):
    """Test creating audit event"""
    repo = AuditRepository(db_session)
    
    event = repo.create_event(
        id="audit_1",
        tenant_id="tenant_1",
        event_type="asset_access",
        event_category="access",
        severity="info",
        actor_id="user_1",
        actor_type="user",
        outcome="success"
    )
    
    assert event.id == "audit_1"
    assert event.event_type == "asset_access"
    assert event.severity == "info"


def test_audit_repository_get_by_severity(db_session):
    """Test getting events by severity"""
    repo = AuditRepository(db_session)
    
    repo.create_event(
        id="audit_1",
        tenant_id="tenant_1",
        event_type="test",
        event_category="test",
        severity="critical",
        actor_id="user_1",
        actor_type="user",
        outcome="success"
    )
    
    repo.create_event(
        id="audit_2",
        tenant_id="tenant_1",
        event_type="test",
        event_category="test",
        severity="info",
        actor_id="user_1",
        actor_type="user",
        outcome="success"
    )
    
    critical = repo.get_by_severity("tenant_1", "critical")
    assert len(critical) == 1
    assert critical[0].severity == "critical"


def test_audit_repository_statistics(db_session):
    """Test audit statistics"""
    repo = AuditRepository(db_session)
    
    repo.create_event(
        id="audit_1",
        tenant_id="tenant_1",
        event_type="test",
        event_category="access",
        severity="info",
        actor_id="user_1",
        actor_type="user",
        outcome="success"
    )
    
    repo.create_event(
        id="audit_2",
        tenant_id="tenant_1",
        event_type="test",
        event_category="modification",
        severity="warning",
        actor_id="user_1",
        actor_type="user",
        outcome="failure"
    )
    
    stats = repo.get_statistics("tenant_1", hours=24)
    
    assert stats["total"] == 2
    assert stats["by_severity"]["info"] == 1
    assert stats["by_outcome"]["success"] == 1


# Approval Repository Tests

def test_approval_repository_create(db_session):
    """Test creating approval request"""
    asset_repo = AssetRepository(db_session)
    approval_repo = ApprovalRepository(db_session)
    
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    approval = approval_repo.create_approval_request(
        id="approval_1",
        asset_id="asset_1",
        tenant_id="tenant_1",
        request_type="deployment",
        requested_by="user_1",
        required_authority=AuthorityLevel.ADMIN,
        risk_tier=RiskTier.HIGH
    )
    
    assert approval.id == "approval_1"
    assert approval.status == ApprovalStatus.PENDING
    assert approval.required_authority == AuthorityLevel.ADMIN


def test_approval_repository_approve(db_session):
    """Test approving request"""
    asset_repo = AssetRepository(db_session)
    approval_repo = ApprovalRepository(db_session)
    
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    approval = approval_repo.create_approval_request(
        id="approval_1",
        asset_id="asset_1",
        tenant_id="tenant_1",
        request_type="deployment",
        requested_by="user_1",
        required_authority=AuthorityLevel.ADMIN,
        risk_tier=RiskTier.HIGH
    )
    
    approved = approval_repo.approve_request("approval_1", "admin_1")
    
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_by == "admin_1"
    assert approved.approved_at is not None


def test_approval_repository_get_pending(db_session):
    """Test getting pending approvals"""
    asset_repo = AssetRepository(db_session)
    approval_repo = ApprovalRepository(db_session)
    
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    approval_repo.create_approval_request(
        id="approval_1",
        asset_id="asset_1",
        tenant_id="tenant_1",
        request_type="deployment",
        requested_by="user_1",
        required_authority=AuthorityLevel.ADMIN,
        risk_tier=RiskTier.HIGH
    )
    
    approval_repo.create_approval_request(
        id="approval_2",
        asset_id="asset_1",
        tenant_id="tenant_1",
        request_type="modification",
        requested_by="user_1",
        required_authority=AuthorityLevel.ADMIN,
        risk_tier=RiskTier.HIGH
    )
    
    pending = approval_repo.get_pending_approvals("tenant_1")
    assert len(pending) == 2


def test_approval_repository_queue_depth(db_session):
    """Test approval queue depth"""
    asset_repo = AssetRepository(db_session)
    approval_repo = ApprovalRepository(db_session)
    
    asset_repo.create_asset(
        id="asset_1",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    
    approval_repo.create_approval_request(
        id="approval_1",
        asset_id="asset_1",
        tenant_id="tenant_1",
        request_type="deployment",
        requested_by="user_1",
        required_authority=AuthorityLevel.ADMIN,
        risk_tier=RiskTier.HIGH
    )
    
    depth = approval_repo.get_approval_queue_depth("tenant_1", RiskTier.HIGH)
    assert depth == 1
