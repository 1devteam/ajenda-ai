"""
Governance Integration Tests (Fixed)
Test full integration of governance with agents and missions

Built with Pride for Obex Blackvault
"""
import pytest
import asyncio
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.base import Base
from backend.database.governance_models import (
    AssetType,
    AssetStatus,
    RiskTier,
    ComplianceStatus
)
from backend.database.repositories import (
    AssetRepository,
    LineageRepository,
    AuditRepository
)
from backend.agents.integration.governance_hooks import governance_hooks


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


@pytest.mark.asyncio
async def test_agent_creation_hook(db_session):
    """Test agent creation hook creates governance records"""
    # Call hook with test DB session
    await governance_hooks.on_agent_created(
        agent_id="test_agent_1",
        agent_type="researcher",
        tenant_id="tenant_1",
        owner_id="user_1",
        name="Test Researcher",
        model="gpt-4",
        capabilities=["research", "analysis"],
        config={"temperature": 0.7},
        db=db_session
    )
    
    # Verify asset created
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.get("test_agent_1")
    
    assert asset is not None
    assert asset.name == "Test Researcher"
    assert asset.asset_type == AssetType.AGENT
    assert asset.owner_id == "user_1"
    assert asset.tenant_id == "tenant_1"
    assert "agent" in asset.tags
    assert "researcher" in asset.tags
    
    # Verify lineage event created
    lineage_repo = LineageRepository(db_session)
    history = lineage_repo.get_asset_history("test_agent_1")
    assert len(history) > 0
    assert history[0].event_type == "created"
    
    # Verify audit event created
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_by_actor("tenant_1", "user_1")
    assert len(events) > 0
    assert any(e.event_type == "agent_created" for e in events)


@pytest.mark.asyncio
async def test_agent_update_hook(db_session):
    """Test agent update hook updates governance records"""
    # Create agent first
    asset_repo = AssetRepository(db_session)
    asset_repo.create_asset(
        id="test_agent_2",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    db_session.commit()
    
    # Call update hook
    await governance_hooks.on_agent_updated(
        agent_id="test_agent_2",
        tenant_id="tenant_1",
        actor_id="user_1",
        changes={"model": "gpt-4-turbo", "temperature": 0.5},
        db=db_session
    )
    
    # Verify asset updated
    asset = asset_repo.get("test_agent_2")
    assert asset.asset_metadata.get("model") == "gpt-4-turbo"
    
    # Verify lineage event
    lineage_repo = LineageRepository(db_session)
    history = lineage_repo.get_asset_history("test_agent_2")
    assert any(e.event_type == "updated" for e in history)
    
    # Verify audit event
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_by_actor("tenant_1", "user_1")
    assert any(e.event_type == "agent_updated" for e in events)


@pytest.mark.asyncio
async def test_agent_deletion_hook(db_session):
    """Test agent deletion hook archives asset"""
    # Create agent first
    asset_repo = AssetRepository(db_session)
    asset_repo.create_asset(
        id="test_agent_3",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    db_session.commit()
    
    # Call deletion hook
    await governance_hooks.on_agent_deleted(
        agent_id="test_agent_3",
        tenant_id="tenant_1",
        actor_id="user_1",
        db=db_session
    )
    
    # Verify asset archived
    asset = asset_repo.get("test_agent_3")
    assert asset.status == AssetStatus.ARCHIVED
    
    # Verify lineage event
    lineage_repo = LineageRepository(db_session)
    history = lineage_repo.get_asset_history("test_agent_3")
    assert any(e.event_type == "deleted" for e in history)


@pytest.mark.asyncio
async def test_mission_start_hook_allows_compliant_agent(db_session):
    """Test mission start hook allows compliant agent"""
    # Create compliant agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="compliant_agent",
        name="Compliant Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    asset_repo.update_compliance_status("compliant_agent", ComplianceStatus.COMPLIANT)
    db_session.commit()
    
    # Call mission start hook
    allowed = await governance_hooks.on_mission_started(
        mission_id="mission_1",
        agent_id="compliant_agent",
        tenant_id="tenant_1",
        objective="Test mission",
        context={},
        db=db_session
    )
    
    assert allowed is True


@pytest.mark.asyncio
async def test_mission_start_hook_blocks_non_compliant_agent(db_session):
    """Test mission start hook blocks non-compliant agent"""
    # Create non-compliant agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="non_compliant_agent",
        name="Non-Compliant Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    asset_repo.update_compliance_status("non_compliant_agent", ComplianceStatus.NON_COMPLIANT)
    db_session.commit()
    
    # Call mission start hook
    allowed = await governance_hooks.on_mission_started(
        mission_id="mission_2",
        agent_id="non_compliant_agent",
        tenant_id="tenant_1",
        objective="Test mission",
        context={},
        db=db_session
    )
    
    assert allowed is False
    
    # Verify audit event for blocked mission
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_by_tenant("tenant_1")
    assert any(
        e.event_type == "mission_blocked" and e.outcome == "blocked"
        for e in events
    )


@pytest.mark.asyncio
async def test_mission_completion_hook(db_session):
    """Test mission completion hook records completion"""
    # Create agent
    asset_repo = AssetRepository(db_session)
    asset_repo.create_asset(
        id="test_agent_4",
        name="Test Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1"
    )
    db_session.commit()
    
    # Call mission completion hook
    await governance_hooks.on_mission_completed(
        mission_id="mission_3",
        agent_id="test_agent_4",
        tenant_id="tenant_1",
        status="success",
        result={"output": "Mission completed successfully"},
        db=db_session
    )
    
    # Verify lineage event
    lineage_repo = LineageRepository(db_session)
    history = lineage_repo.get_asset_history("test_agent_4")
    assert any(e.event_type == "mission_completed" for e in history)
    
    # Verify audit event
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_by_tenant("tenant_1")
    assert any(
        e.event_type == "mission_completed" and e.outcome == "success"
        for e in events
    )


@pytest.mark.asyncio
async def test_full_agent_lifecycle(db_session):
    """Test complete agent lifecycle with governance"""
    agent_id = "lifecycle_agent"
    tenant_id = "tenant_1"
    owner_id = "user_1"
    
    # 1. Create agent
    await governance_hooks.on_agent_created(
        agent_id=agent_id,
        agent_type="analyst",
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Lifecycle Test Agent",
        model="gpt-4",
        capabilities=["analysis"],
        config={},
        db=db_session
    )
    
    # Verify creation
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.get(agent_id)
    assert asset is not None
    
    # 2. Update agent
    await governance_hooks.on_agent_updated(
        agent_id=agent_id,
        tenant_id=tenant_id,
        actor_id=owner_id,
        changes={"version": "2.0"},
        db=db_session
    )
    
    # 3. Run mission
    allowed = await governance_hooks.on_mission_started(
        mission_id="lifecycle_mission",
        agent_id=agent_id,
        tenant_id=tenant_id,
        objective="Test objective",
        context={},
        db=db_session
    )
    assert allowed is True
    
    await governance_hooks.on_mission_completed(
        mission_id="lifecycle_mission",
        agent_id=agent_id,
        tenant_id=tenant_id,
        status="success",
        result={},
        db=db_session
    )
    
    # 4. Delete agent
    await governance_hooks.on_agent_deleted(
        agent_id=agent_id,
        tenant_id=tenant_id,
        actor_id=owner_id,
        db=db_session
    )
    
    # Verify complete history
    lineage_repo = LineageRepository(db_session)
    history = lineage_repo.get_asset_history(agent_id)
    
    event_types = [e.event_type for e in history]
    assert "created" in event_types
    assert "updated" in event_types
    assert "mission_completed" in event_types
    assert "deleted" in event_types
    
    # Verify audit trail
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_by_tenant(tenant_id)
    
    audit_types = [e.event_type for e in events]
    assert "agent_created" in audit_types
    assert "agent_updated" in audit_types
    assert "mission_started" in audit_types
    assert "mission_completed" in audit_types
    assert "agent_deleted" in audit_types
