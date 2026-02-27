"""
Tests for Audit Monitor.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.compliance.audit_monitor import (
    get_audit_monitor,
    AuditEvent,
    AuditEventType,
    EventResult,
    Anomaly,
    AnomalyType,
)
from backend.agents.registry.asset_registry import get_registry, AIAsset, AssetType, AssetStatus


@pytest.fixture(autouse=True)
def clear_monitor():
    """Clear monitor before each test."""
    monitor = get_audit_monitor()
    monitor.clear()
    yield
    monitor.clear()


@pytest.fixture
def monitor():
    """Get audit monitor instance."""
    return get_audit_monitor()


@pytest.fixture
def sample_event(monitor):
    """Create a sample audit event."""
    event = monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate_policy",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
        policy_ids=["policy-001"],
        context={"location": "production"},
    )
    return event


# ============================================================================
# Event Tracking Tests
# ============================================================================

def test_track_event(monitor):
    """Test tracking an audit event."""
    event = monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate_policy",
        result=EventResult.ALLOWED,
    )
    
    assert event.event_id
    assert event.event_type == AuditEventType.POLICY_EVALUATION
    assert event.actor == "user-001"
    assert event.result == EventResult.ALLOWED


def test_track_event_with_asset(monitor):
    """Test tracking event with asset."""
    event = monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-001",
        action="access_asset",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    
    assert event.asset_id == "agent-001"


def test_track_event_with_policies(monitor):
    """Test tracking event with policies."""
    event = monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
        policy_ids=["policy-001", "policy-002"],
    )
    
    assert len(event.policy_ids) == 2
    assert "policy-001" in event.policy_ids


def test_track_event_with_metadata(monitor):
    """Test tracking event with metadata."""
    event = monitor.track_event(
        event_type=AuditEventType.APPROVAL_REQUEST,
        actor="user-001",
        action="request_approval",
        result=EventResult.ALLOWED,
        metadata={"risk_tier": "high"},
    )
    
    assert event.metadata["risk_tier"] == "high"


def test_track_event_with_context(monitor):
    """Test tracking event with context."""
    event = monitor.track_event(
        event_type=AuditEventType.COMPLIANCE_CHECK,
        actor="system",
        action="run_check",
        result=EventResult.ALLOWED,
        context={"check_type": "asset_compliance"},
    )
    
    assert event.context["check_type"] == "asset_compliance"


# ============================================================================
# Event Retrieval Tests
# ============================================================================

def test_get_event(monitor, sample_event):
    """Test getting event by ID."""
    event = monitor.get_event(sample_event.event_id)
    
    assert event is not None
    assert event.event_id == sample_event.event_id


def test_get_event_not_found(monitor):
    """Test getting non-existent event."""
    event = monitor.get_event("nonexistent")
    
    assert event is None


def test_get_events_all(monitor):
    """Test getting all events."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-002",
        action="access",
        result=EventResult.DENIED,
    )
    
    events = monitor.get_events()
    
    assert len(events) == 2


def test_get_events_by_type(monitor):
    """Test filtering events by type."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-002",
        action="access",
        result=EventResult.DENIED,
    )
    
    events = monitor.get_events(event_type=AuditEventType.POLICY_EVALUATION)
    
    assert len(events) == 1
    assert events[0].event_type == AuditEventType.POLICY_EVALUATION


def test_get_events_by_actor(monitor):
    """Test filtering events by actor."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-002",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    
    events = monitor.get_events(actor="user-001")
    
    assert len(events) == 1
    assert events[0].actor == "user-001"


def test_get_events_by_asset(monitor):
    """Test filtering events by asset."""
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-001",
        action="access",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-002",
        action="access",
        result=EventResult.ALLOWED,
        asset_id="agent-002",
    )
    
    events = monitor.get_events(asset_id="agent-001")
    
    assert len(events) == 1
    assert events[0].asset_id == "agent-001"


def test_get_events_by_result(monitor):
    """Test filtering events by result."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-002",
        action="evaluate",
        result=EventResult.DENIED,
    )
    
    events = monitor.get_events(result=EventResult.DENIED)
    
    assert len(events) == 1
    assert events[0].result == EventResult.DENIED


def test_get_events_limit(monitor):
    """Test limiting number of events."""
    for i in range(10):
        monitor.track_event(
            event_type=AuditEventType.POLICY_EVALUATION,
            actor=f"user-{i}",
            action="evaluate",
            result=EventResult.ALLOWED,
        )
    
    events = monitor.get_events(limit=5)
    
    assert len(events) == 5


# ============================================================================
# Audit Trail Tests
# ============================================================================

def test_get_audit_trail(monitor):
    """Test getting audit trail for asset."""
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-001",
        action="access",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    monitor.track_event(
        event_type=AuditEventType.ASSET_UPDATE,
        actor="user-002",
        action="update",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    
    trail = monitor.get_audit_trail("agent-001")
    
    assert len(trail) == 2
    assert all(e.asset_id == "agent-001" for e in trail)


def test_get_audit_trail_chronological(monitor):
    """Test audit trail is chronological."""
    event1 = monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-001",
        action="access",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    event2 = monitor.track_event(
        event_type=AuditEventType.ASSET_UPDATE,
        actor="user-002",
        action="update",
        result=EventResult.ALLOWED,
        asset_id="agent-001",
    )
    
    trail = monitor.get_audit_trail("agent-001")
    
    assert trail[0].timestamp < trail[1].timestamp


def test_get_audit_trail_by_actor(monitor):
    """Test getting audit trail by actor."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-002",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    
    trail = monitor.get_audit_trail_by_actor("user-001")
    
    assert len(trail) == 1
    assert trail[0].actor == "user-001"


# ============================================================================
# Anomaly Detection Tests
# ============================================================================

def test_detect_repeated_denials(monitor):
    """Test detecting repeated denial anomaly."""
    # Create 5 denials from same user
    for _ in range(5):
        monitor.track_event(
            event_type=AuditEventType.POLICY_EVALUATION,
            actor="user-001",
            action="evaluate",
            result=EventResult.DENIED,
        )
    
    anomalies = monitor.detect_anomalies()
    
    # Should detect repeated denials
    repeated_denials = [a for a in anomalies if a.anomaly_type == AnomalyType.REPEATED_DENIALS]
    assert len(repeated_denials) > 0


def test_detect_unusual_volume(monitor):
    """Test detecting unusual volume anomaly."""
    # Create 20 events from same user
    for _ in range(20):
        monitor.track_event(
            event_type=AuditEventType.ASSET_ACCESS,
            actor="user-001",
            action="access",
            result=EventResult.ALLOWED,
        )
    
    anomalies = monitor.detect_anomalies()
    
    # Should detect unusual volume
    unusual_volume = [a for a in anomalies if a.anomaly_type == AnomalyType.UNUSUAL_VOLUME]
    assert len(unusual_volume) > 0


# ============================================================================
# Statistics Tests
# ============================================================================

def test_get_statistics(monitor):
    """Test getting audit statistics."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.ASSET_ACCESS,
        actor="user-002",
        action="access",
        result=EventResult.DENIED,
    )
    
    stats = monitor.get_statistics()
    
    assert stats["total_events"] == 2
    assert "by_type" in stats
    assert "by_result" in stats


def test_statistics_by_type(monitor):
    """Test statistics by event type."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-002",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    
    stats = monitor.get_statistics()
    
    assert stats["by_type"]["policy_evaluation"] == 2


def test_statistics_by_result(monitor):
    """Test statistics by result."""
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-001",
        action="evaluate",
        result=EventResult.ALLOWED,
    )
    monitor.track_event(
        event_type=AuditEventType.POLICY_EVALUATION,
        actor="user-002",
        action="evaluate",
        result=EventResult.DENIED,
    )
    
    stats = monitor.get_statistics()
    
    assert stats["by_result"]["allowed"] == 1
    assert stats["by_result"]["denied"] == 1


# ============================================================================
# Serialization Tests
# ============================================================================

def test_audit_event_to_dict(sample_event):
    """Test audit event serialization."""
    data = sample_event.to_dict()
    
    assert data["event_id"] == sample_event.event_id
    assert data["event_type"] == sample_event.event_type.value
    assert data["actor"] == sample_event.actor


def test_anomaly_to_dict(monitor):
    """Test anomaly serialization."""
    # Create anomaly
    for _ in range(5):
        monitor.track_event(
            event_type=AuditEventType.POLICY_EVALUATION,
            actor="user-001",
            action="evaluate",
            result=EventResult.DENIED,
        )
    
    anomalies = monitor.detect_anomalies()
    
    if anomalies:
        data = anomalies[0].to_dict()
        assert "anomaly_id" in data
        assert "anomaly_type" in data
