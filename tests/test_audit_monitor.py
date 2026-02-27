"""
Comprehensive tests for Audit Monitor - Week 2

Tests all functionality: event tracking, querying, audit trails,
anomaly detection, and statistics.

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


# ============================================================================
# Fixtures
# ============================================================================

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
def sample_event():
    """Create a sample audit event."""
    return AuditEvent(
        event_id="event-001",
        event_type=AuditEventType.POLICY_EVALUATION,
        timestamp=datetime.utcnow(),
        actor="user-001",
        action="Evaluated policy for asset access",
        result=EventResult.ALLOWED,
        asset_id="asset-001",
        policy_ids=["policy-001"],
        metadata={"duration_ms": 50},
        context={"location": "production"},
    )


# ============================================================================
# Event Tracking Tests
# ============================================================================

def test_track_event(monitor, sample_event):
    """Test tracking a single event."""
    monitor.track_event(sample_event)
    
    retrieved = monitor.get_event(sample_event.event_id)
    assert retrieved is not None
    assert retrieved.event_id == sample_event.event_id
    assert retrieved.event_type == sample_event.event_type
    assert retrieved.actor == sample_event.actor


def test_track_multiple_events(monitor):
    """Test tracking multiple events."""
    events = []
    for i in range(5):
        event = AuditEvent(
            event_id=f"event-{i:03d}",
            event_type=AuditEventType.ASSET_REGISTERED,
            timestamp=datetime.utcnow(),
            actor=f"user-{i:03d}",
            action=f"Registered asset {i}",
            result=EventResult.SUCCESS,
            asset_id=f"asset-{i:03d}",
        )
        events.append(event)
        monitor.track_event(event)
    
    # Verify all events tracked
    for event in events:
        retrieved = monitor.get_event(event.event_id)
        assert retrieved is not None
        assert retrieved.event_id == event.event_id


def test_event_indexing(monitor):
    """Test that events are properly indexed."""
    # Create events with different attributes
    event1 = AuditEvent(
        event_id="event-001",
        event_type=AuditEventType.POLICY_EVALUATION,
        timestamp=datetime.utcnow(),
        actor="user-001",
        action="Test",
        result=EventResult.ALLOWED,
        asset_id="asset-001",
    )
    event2 = AuditEvent(
        event_id="event-002",
        event_type=AuditEventType.APPROVAL_REQUESTED,
        timestamp=datetime.utcnow(),
        actor="user-002",
        action="Test",
        result=EventResult.PENDING,
        asset_id="asset-001",
    )
    
    monitor.track_event(event1)
    monitor.track_event(event2)
    
    # Query by type
    policy_events = monitor.get_events(event_type=AuditEventType.POLICY_EVALUATION)
    assert len(policy_events) == 1
    assert policy_events[0].event_id == "event-001"
    
    # Query by actor
    user1_events = monitor.get_events(actor="user-001")
    assert len(user1_events) == 1
    assert user1_events[0].event_id == "event-001"
    
    # Query by asset
    asset_events = monitor.get_events(asset_id="asset-001")
    assert len(asset_events) == 2
    
    # Query by result
    allowed_events = monitor.get_events(result=EventResult.ALLOWED)
    assert len(allowed_events) == 1


# ============================================================================
# Event Querying Tests
# ============================================================================

def test_get_events_with_time_filter(monitor):
    """Test querying events with time filters."""
    now = datetime.utcnow()
    old_time = now - timedelta(hours=2)
    recent_time = now - timedelta(minutes=30)
    
    # Create events at different times
    old_event = AuditEvent(
        event_id="event-old",
        event_type=AuditEventType.USER_ACTION,
        timestamp=old_time,
        actor="user-001",
        action="Old action",
        result=EventResult.SUCCESS,
    )
    recent_event = AuditEvent(
        event_id="event-recent",
        event_type=AuditEventType.USER_ACTION,
        timestamp=recent_time,
        actor="user-001",
        action="Recent action",
        result=EventResult.SUCCESS,
    )
    
    monitor.track_event(old_event)
    monitor.track_event(recent_event)
    
    # Query with start_time
    recent_events = monitor.get_events(start_time=now - timedelta(hours=1))
    assert len(recent_events) == 1
    assert recent_events[0].event_id == "event-recent"
    
    # Query with end_time
    old_events = monitor.get_events(end_time=now - timedelta(hours=1))
    assert len(old_events) == 1
    assert old_events[0].event_id == "event-old"


def test_get_events_with_limit(monitor):
    """Test querying events with limit."""
    # Create 10 events
    for i in range(10):
        event = AuditEvent(
            event_id=f"event-{i:03d}",
            event_type=AuditEventType.USER_ACTION,
            timestamp=datetime.utcnow(),
            actor="user-001",
            action=f"Action {i}",
            result=EventResult.SUCCESS,
        )
        monitor.track_event(event)
    
    # Query with limit
    events = monitor.get_events(limit=5)
    assert len(events) == 5


def test_get_events_sorted_by_timestamp(monitor):
    """Test that events are sorted by timestamp (newest first)."""
    now = datetime.utcnow()
    
    # Create events in random order
    event1 = AuditEvent(
        event_id="event-001",
        event_type=AuditEventType.USER_ACTION,
        timestamp=now - timedelta(minutes=10),
        actor="user-001",
        action="First",
        result=EventResult.SUCCESS,
    )
    event2 = AuditEvent(
        event_id="event-002",
        event_type=AuditEventType.USER_ACTION,
        timestamp=now - timedelta(minutes=5),
        actor="user-001",
        action="Second",
        result=EventResult.SUCCESS,
    )
    event3 = AuditEvent(
        event_id="event-003",
        event_type=AuditEventType.USER_ACTION,
        timestamp=now,
        actor="user-001",
        action="Third",
        result=EventResult.SUCCESS,
    )
    
    monitor.track_event(event1)
    monitor.track_event(event3)
    monitor.track_event(event2)
    
    # Query all events
    events = monitor.get_events()
    assert len(events) == 3
    assert events[0].event_id == "event-003"  # Newest first
    assert events[1].event_id == "event-002"
    assert events[2].event_id == "event-001"


# ============================================================================
# Audit Trail Tests
# ============================================================================

def test_get_audit_trail(monitor):
    """Test getting complete audit trail for an asset."""
    now = datetime.utcnow()
    
    # Create events for asset lifecycle
    events = [
        AuditEvent(
            event_id="event-001",
            event_type=AuditEventType.ASSET_REGISTERED,
            timestamp=now - timedelta(hours=2),
            actor="user-001",
            action="Registered asset",
            result=EventResult.SUCCESS,
            asset_id="asset-001",
        ),
        AuditEvent(
            event_id="event-002",
            event_type=AuditEventType.TAG_ADDED,
            timestamp=now - timedelta(hours=1),
            actor="user-001",
            action="Added tag",
            result=EventResult.SUCCESS,
            asset_id="asset-001",
        ),
        AuditEvent(
            event_id="event-003",
            event_type=AuditEventType.RISK_ASSESSED,
            timestamp=now,
            actor="system",
            action="Assessed risk",
            result=EventResult.SUCCESS,
            asset_id="asset-001",
        ),
    ]
    
    for event in events:
        monitor.track_event(event)
    
    # Get audit trail
    trail = monitor.get_audit_trail("asset-001")
    assert len(trail) == 3
    # Should be sorted chronologically (oldest first)
    assert trail[0].event_id == "event-001"
    assert trail[1].event_id == "event-002"
    assert trail[2].event_id == "event-003"


def test_get_actor_history(monitor):
    """Test getting event history for an actor."""
    # Create events by different actors
    for i in range(3):
        event = AuditEvent(
            event_id=f"event-user1-{i}",
            event_type=AuditEventType.USER_ACTION,
            timestamp=datetime.utcnow(),
            actor="user-001",
            action=f"Action {i}",
            result=EventResult.SUCCESS,
        )
        monitor.track_event(event)
    
    for i in range(2):
        event = AuditEvent(
            event_id=f"event-user2-{i}",
            event_type=AuditEventType.USER_ACTION,
            timestamp=datetime.utcnow(),
            actor="user-002",
            action=f"Action {i}",
            result=EventResult.SUCCESS,
        )
        monitor.track_event(event)
    
    # Get history for user-001
    history = monitor.get_actor_history("user-001")
    assert len(history) == 3
    assert all(e.actor == "user-001" for e in history)


# ============================================================================
# Anomaly Detection Tests
# ============================================================================

def test_detect_repeated_denials(monitor):
    """Test detection of repeated denial attempts."""
    now = datetime.utcnow()
    
    # Create 5 denied events in 15 minutes (should trigger anomaly)
    for i in range(5):
        event = AuditEvent(
            event_id=f"event-{i:03d}",
            event_type=AuditEventType.POLICY_EVALUATION,
            timestamp=now - timedelta(minutes=i),
            actor="user-001",
            action="Attempted access",
            result=EventResult.DENIED,
            asset_id="asset-001",
        )
        monitor.track_event(event)
    
    # Check anomalies
    anomalies = monitor.detect_anomalies()
    assert len(anomalies) > 0
    
    # Find repeated denials anomaly
    denial_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.REPEATED_DENIALS]
    assert len(denial_anomalies) > 0
    
    anomaly = denial_anomalies[0]
    assert anomaly.severity == "high"
    assert "user-001" in anomaly.affected_users


def test_detect_unusual_volume(monitor):
    """Test detection of unusual event volume."""
    now = datetime.utcnow()
    
    # Create 50 events of same type in 5 minutes (should trigger anomaly)
    for i in range(50):
        event = AuditEvent(
            event_id=f"event-{i:03d}",
            event_type=AuditEventType.POLICY_EVALUATION,
            timestamp=now - timedelta(seconds=i),
            actor=f"user-{i:03d}",
            action="Action",
            result=EventResult.ALLOWED,
        )
        monitor.track_event(event)
    
    # Check anomalies
    anomalies = monitor.detect_anomalies()
    
    # Find unusual volume anomaly
    volume_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.UNUSUAL_VOLUME]
    assert len(volume_anomalies) > 0
    
    anomaly = volume_anomalies[0]
    assert anomaly.severity == "medium"


def test_detect_off_hours_access(monitor):
    """Test detection of off-hours access."""
    # Create event at 10pm (off-hours)
    off_hours_time = datetime.utcnow().replace(hour=22, minute=0, second=0)
    
    event = AuditEvent(
        event_id="event-001",
        event_type=AuditEventType.ASSET_REGISTERED,
        timestamp=off_hours_time,
        actor="user-001",
        action="Registered asset",
        result=EventResult.SUCCESS,
        asset_id="asset-001",
    )
    monitor.track_event(event)
    
    # Check anomalies
    anomalies = monitor.detect_anomalies()
    
    # Find off-hours anomaly
    off_hours_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.OFF_HOURS_ACCESS]
    assert len(off_hours_anomalies) > 0
    
    anomaly = off_hours_anomalies[0]
    assert anomaly.severity == "low"
    assert "user-001" in anomaly.affected_users


def test_get_anomaly(monitor):
    """Test retrieving specific anomaly."""
    # Trigger anomaly
    now = datetime.utcnow()
    for i in range(5):
        event = AuditEvent(
            event_id=f"event-{i:03d}",
            event_type=AuditEventType.POLICY_EVALUATION,
            timestamp=now - timedelta(minutes=i),
            actor="user-001",
            action="Attempted access",
            result=EventResult.DENIED,
        )
        monitor.track_event(event)
    
    # Get anomalies
    anomalies = monitor.detect_anomalies()
    assert len(anomalies) > 0
    
    # Get specific anomaly
    anomaly_id = anomalies[0].anomaly_id
    retrieved = monitor.get_anomaly(anomaly_id)
    assert retrieved is not None
    assert retrieved.anomaly_id == anomaly_id


# ============================================================================
# Statistics Tests
# ============================================================================

def test_get_statistics(monitor):
    """Test getting audit statistics."""
    # Create various events
    events = [
        AuditEvent(
            event_id="event-001",
            event_type=AuditEventType.POLICY_EVALUATION,
            timestamp=datetime.utcnow(),
            actor="user-001",
            action="Test",
            result=EventResult.ALLOWED,
            asset_id="asset-001",
        ),
        AuditEvent(
            event_id="event-002",
            event_type=AuditEventType.POLICY_EVALUATION,
            timestamp=datetime.utcnow(),
            actor="user-002",
            action="Test",
            result=EventResult.DENIED,
            asset_id="asset-002",
        ),
        AuditEvent(
            event_id="event-003",
            event_type=AuditEventType.APPROVAL_REQUESTED,
            timestamp=datetime.utcnow(),
            actor="user-001",
            action="Test",
            result=EventResult.PENDING,
            asset_id="asset-003",
        ),
    ]
    
    for event in events:
        monitor.track_event(event)
    
    # Get statistics
    stats = monitor.get_statistics()
    
    assert stats["total_events"] == 3
    assert stats["unique_actors"] == 2
    assert stats["unique_assets"] == 3
    assert stats["by_type"]["policy_evaluation"] == 2
    assert stats["by_type"]["approval_requested"] == 1
    assert stats["by_result"]["allowed"] == 1
    assert stats["by_result"]["denied"] == 1
    assert stats["by_result"]["pending"] == 1


def test_statistics_recent_24h(monitor):
    """Test statistics for recent 24 hours."""
    now = datetime.utcnow()
    
    # Create old event (25 hours ago)
    old_event = AuditEvent(
        event_id="event-old",
        event_type=AuditEventType.USER_ACTION,
        timestamp=now - timedelta(hours=25),
        actor="user-001",
        action="Old action",
        result=EventResult.SUCCESS,
    )
    monitor.track_event(old_event)
    
    # Create recent events
    for i in range(3):
        event = AuditEvent(
            event_id=f"event-recent-{i}",
            event_type=AuditEventType.USER_ACTION,
            timestamp=now - timedelta(hours=i),
            actor="user-001",
            action="Recent action",
            result=EventResult.SUCCESS,
        )
        monitor.track_event(event)
    
    # Get statistics
    stats = monitor.get_statistics()
    
    assert stats["total_events"] == 4
    assert stats["recent_24h"] == 3  # Only recent events


# ============================================================================
# Data Model Tests
# ============================================================================

def test_audit_event_to_dict(sample_event):
    """Test converting AuditEvent to dictionary."""
    data = sample_event.to_dict()
    
    assert data["event_id"] == sample_event.event_id
    assert data["event_type"] == sample_event.event_type.value
    assert data["actor"] == sample_event.actor
    assert data["action"] == sample_event.action
    assert data["result"] == sample_event.result.value
    assert data["asset_id"] == sample_event.asset_id
    assert data["policy_ids"] == sample_event.policy_ids
    assert data["metadata"] == sample_event.metadata
    assert data["context"] == sample_event.context


def test_audit_event_from_dict(sample_event):
    """Test creating AuditEvent from dictionary."""
    data = sample_event.to_dict()
    restored = AuditEvent.from_dict(data)
    
    assert restored.event_id == sample_event.event_id
    assert restored.event_type == sample_event.event_type
    assert restored.actor == sample_event.actor
    assert restored.action == sample_event.action
    assert restored.result == sample_event.result
    assert restored.asset_id == sample_event.asset_id


def test_anomaly_to_dict():
    """Test converting Anomaly to dictionary."""
    anomaly = Anomaly(
        anomaly_id="anomaly-001",
        anomaly_type=AnomalyType.REPEATED_DENIALS,
        detected_at=datetime.utcnow(),
        description="Test anomaly",
        severity="high",
        affected_events=["event-001"],
        affected_assets=["asset-001"],
        affected_users=["user-001"],
        metadata={"count": 5},
    )
    
    data = anomaly.to_dict()
    
    assert data["anomaly_id"] == anomaly.anomaly_id
    assert data["anomaly_type"] == anomaly.anomaly_type.value
    assert data["description"] == anomaly.description
    assert data["severity"] == anomaly.severity
    assert data["affected_events"] == anomaly.affected_events
    assert data["affected_assets"] == anomaly.affected_assets
    assert data["affected_users"] == anomaly.affected_users
    assert data["metadata"] == anomaly.metadata


# ============================================================================
# Edge Cases
# ============================================================================

def test_get_nonexistent_event(monitor):
    """Test getting event that doesn't exist."""
    event = monitor.get_event("nonexistent")
    assert event is None


def test_get_nonexistent_anomaly(monitor):
    """Test getting anomaly that doesn't exist."""
    anomaly = monitor.get_anomaly("nonexistent")
    assert anomaly is None


def test_get_events_no_matches(monitor, sample_event):
    """Test querying events with no matches."""
    monitor.track_event(sample_event)
    
    events = monitor.get_events(actor="nonexistent-user")
    assert len(events) == 0


def test_get_audit_trail_no_events(monitor):
    """Test getting audit trail for asset with no events."""
    trail = monitor.get_audit_trail("nonexistent-asset")
    assert len(trail) == 0


def test_clear_monitor(monitor, sample_event):
    """Test clearing monitor."""
    monitor.track_event(sample_event)
    assert len(monitor.get_events()) == 1
    
    monitor.clear()
    assert len(monitor.get_events()) == 0
    assert len(monitor.detect_anomalies()) == 0
    
    stats = monitor.get_statistics()
    assert stats["total_events"] == 0
    assert stats["total_anomalies"] == 0


def test_singleton_pattern():
    """Test that monitor is a singleton."""
    monitor1 = get_audit_monitor()
    monitor2 = get_audit_monitor()
    
    assert monitor1 is monitor2
