"""
Audit Monitor - Real-time governance event tracking.

Tracks all governance events (policy evaluations, approvals, risk assessments),
monitors asset lifecycle changes, detects anomalies, and generates audit trails.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid


# ============================================================================
# Enums
# ============================================================================


class AuditEventType(Enum):
    """Types of audit events."""

    POLICY_EVALUATION = "policy_evaluation"
    POLICY_CREATED = "policy_created"
    POLICY_UPDATED = "policy_updated"
    POLICY_ACTIVATED = "policy_activated"
    POLICY_DEACTIVATED = "policy_deactivated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_ESCALATED = "approval_escalated"
    RISK_ASSESSED = "risk_assessed"
    ASSET_REGISTERED = "asset_registered"
    ASSET_UPDATED = "asset_updated"
    ASSET_DEPRECATED = "asset_deprecated"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
    COMPLIANCE_CHECK = "compliance_check"
    ALERT_TRIGGERED = "alert_triggered"
    USER_ACTION = "user_action"
    SYSTEM_ACTION = "system_action"


class EventResult(Enum):
    """Result of an event."""

    ALLOWED = "allowed"
    DENIED = "denied"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"


class AnomalyType(Enum):
    """Types of anomalies."""

    UNUSUAL_VOLUME = "unusual_volume"  # Spike in events
    UNUSUAL_PATTERN = "unusual_pattern"  # Unusual access pattern
    REPEATED_DENIALS = "repeated_denials"  # Multiple denied attempts
    PRIVILEGE_ESCALATION = "privilege_escalation"  # User trying higher privileges
    OFF_HOURS_ACCESS = "off_hours_access"  # Access outside normal hours
    GEOGRAPHIC_ANOMALY = "geographic_anomaly"  # Access from unusual location
    RAPID_CHANGES = "rapid_changes"  # Too many changes too quickly


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class AuditEvent:
    """
    Represents a governance audit event.

    Immutable record of what happened, when, who did it, and what the result was.
    """

    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    actor: str  # User ID or "system"
    action: str  # Human-readable description
    result: EventResult
    asset_id: Optional[str] = None
    policy_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "result": self.result.value,
            "asset_id": self.asset_id,
            "policy_ids": self.policy_ids,
            "metadata": self.metadata,
            "context": self.context,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AuditEvent":
        """Create from dictionary."""
        return AuditEvent(
            event_id=data["event_id"],
            event_type=AuditEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            actor=data["actor"],
            action=data["action"],
            result=EventResult(data["result"]),
            asset_id=data.get("asset_id"),
            policy_ids=data.get("policy_ids", []),
            metadata=data.get("metadata", {}),
            context=data.get("context", {}),
        )


@dataclass
class Anomaly:
    """
    Represents a detected anomaly in audit events.
    """

    anomaly_id: str
    anomaly_type: AnomalyType
    detected_at: datetime
    description: str
    severity: str  # "low", "medium", "high", "critical"
    affected_events: List[str]  # Event IDs
    affected_assets: List[str]
    affected_users: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "detected_at": self.detected_at.isoformat(),
            "description": self.description,
            "severity": self.severity,
            "affected_events": self.affected_events,
            "affected_assets": self.affected_assets,
            "affected_users": self.affected_users,
            "metadata": self.metadata,
        }


# ============================================================================
# Audit Monitor
# ============================================================================


class AuditMonitor:
    """
    Monitors and tracks all governance events.

    Provides audit trail, anomaly detection, and event querying.
    Singleton pattern ensures single source of truth.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._events: Dict[str, AuditEvent] = {}
        self._anomalies: Dict[str, Anomaly] = {}
        self._event_index: Dict[str, List[str]] = {
            "by_type": {},
            "by_actor": {},
            "by_asset": {},
            "by_result": {},
        }
        self._initialized = True

    def track_event(self, event: AuditEvent) -> None:
        """
        Track a governance event.

        Args:
            event: Event to track
        """
        # Store event
        self._events[event.event_id] = event

        # Update indexes
        event_type = event.event_type.value
        if event_type not in self._event_index["by_type"]:
            self._event_index["by_type"][event_type] = []
        self._event_index["by_type"][event_type].append(event.event_id)

        if event.actor not in self._event_index["by_actor"]:
            self._event_index["by_actor"][event.actor] = []
        self._event_index["by_actor"][event.actor].append(event.event_id)

        if event.asset_id:
            if event.asset_id not in self._event_index["by_asset"]:
                self._event_index["by_asset"][event.asset_id] = []
            self._event_index["by_asset"][event.asset_id].append(event.event_id)

        result = event.result.value
        if result not in self._event_index["by_result"]:
            self._event_index["by_result"][result] = []
        self._event_index["by_result"][result].append(event.event_id)

        # Check for anomalies
        self._check_for_anomalies(event)

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        """Get event by ID."""
        return self._events.get(event_id)

    def get_events(
        self,
        event_type: Optional[AuditEventType] = None,
        actor: Optional[str] = None,
        asset_id: Optional[str] = None,
        result: Optional[EventResult] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """
        Query events with filters.

        Args:
            event_type: Filter by event type
            actor: Filter by actor
            asset_id: Filter by asset
            result: Filter by result
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of events to return

        Returns:
            List of matching events
        """
        # Start with all events or filtered by index
        if event_type:
            event_ids = self._event_index["by_type"].get(event_type.value, [])
        elif actor:
            event_ids = self._event_index["by_actor"].get(actor, [])
        elif asset_id:
            event_ids = self._event_index["by_asset"].get(asset_id, [])
        elif result:
            event_ids = self._event_index["by_result"].get(result.value, [])
        else:
            event_ids = list(self._events.keys())

        # Get events
        events = [self._events[eid] for eid in event_ids if eid in self._events]

        # Apply additional filters
        if actor and not event_type:
            events = [e for e in events if e.actor == actor]
        if asset_id and not event_type:
            events = [e for e in events if e.asset_id == asset_id]
        if result and not event_type:
            events = [e for e in events if e.result == result]
        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]

        # Sort by timestamp (newest first) and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def get_audit_trail(self, asset_id: str) -> List[AuditEvent]:
        """
        Get complete audit trail for an asset.

        Args:
            asset_id: Asset ID

        Returns:
            List of events for this asset, sorted chronologically
        """
        event_ids = self._event_index["by_asset"].get(asset_id, [])
        events = [self._events[eid] for eid in event_ids if eid in self._events]
        events.sort(key=lambda e: e.timestamp)
        return events

    def get_actor_history(self, actor: str, limit: int = 100) -> List[AuditEvent]:
        """
        Get event history for an actor.

        Args:
            actor: Actor (user ID)
            limit: Maximum number of events

        Returns:
            List of events by this actor
        """
        return self.get_events(actor=actor, limit=limit)

    def detect_anomalies(self) -> List[Anomaly]:
        """
        Detect anomalies in recent events.

        Returns:
            List of detected anomalies
        """
        return list(self._anomalies.values())

    def get_anomaly(self, anomaly_id: str) -> Optional[Anomaly]:
        """Get anomaly by ID."""
        return self._anomalies.get(anomaly_id)

    def _check_for_anomalies(self, event: AuditEvent) -> None:
        """
        Check if event represents an anomaly.

        Args:
            event: Event to check
        """
        # Check for repeated denials
        if event.result == EventResult.DENIED:
            self._check_repeated_denials(event)

        # Check for unusual volume
        self._check_unusual_volume(event)

        # Check for off-hours access
        self._check_off_hours_access(event)

    def _check_repeated_denials(self, event: AuditEvent) -> None:
        """Check for repeated denial attempts."""
        # Get recent denials by this actor
        recent_time = datetime.utcnow() - timedelta(minutes=15)
        recent_denials = [
            e
            for e in self.get_events(actor=event.actor, limit=50)
            if e.result == EventResult.DENIED and e.timestamp >= recent_time
        ]

        # If 5+ denials in 15 minutes, flag anomaly
        if len(recent_denials) >= 5:
            anomaly_id = f"anomaly-{uuid.uuid4()}"
            anomaly = Anomaly(
                anomaly_id=anomaly_id,
                anomaly_type=AnomalyType.REPEATED_DENIALS,
                detected_at=datetime.utcnow(),
                description=f"Actor {event.actor} has {len(recent_denials)} denied attempts in 15 minutes",  # noqa: E501
                severity="high",
                affected_events=[e.event_id for e in recent_denials],
                affected_assets=[e.asset_id for e in recent_denials if e.asset_id],
                affected_users=[event.actor],
                metadata={"denial_count": len(recent_denials)},
            )
            self._anomalies[anomaly_id] = anomaly

    def _check_unusual_volume(self, event: AuditEvent) -> None:
        """Check for unusual event volume."""
        # Get events in last 5 minutes
        recent_time = datetime.utcnow() - timedelta(minutes=5)
        recent_events = [
            e
            for e in self.get_events(event_type=event.event_type, limit=200)
            if e.timestamp >= recent_time
        ]

        # If 50+ events of same type in 5 minutes, flag anomaly
        if len(recent_events) >= 50:
            anomaly_id = f"anomaly-{uuid.uuid4()}"
            anomaly = Anomaly(
                anomaly_id=anomaly_id,
                anomaly_type=AnomalyType.UNUSUAL_VOLUME,
                detected_at=datetime.utcnow(),
                description=f"Unusual volume of {event.event_type.value} events: {len(recent_events)} in 5 minutes",  # noqa: E501
                severity="medium",
                affected_events=[e.event_id for e in recent_events[-10:]],  # Last 10
                affected_assets=list(
                    set(e.asset_id for e in recent_events if e.asset_id)
                ),
                affected_users=list(set(e.actor for e in recent_events)),
                metadata={"event_count": len(recent_events)},
            )
            self._anomalies[anomaly_id] = anomaly

    def _check_off_hours_access(self, event: AuditEvent) -> None:
        """Check for off-hours access."""
        # Business hours: 8am-6pm weekdays
        hour = event.timestamp.hour
        weekday = event.timestamp.weekday()

        is_off_hours = (
            weekday >= 5 or hour < 8 or hour >= 18  # Weekend  # Before 8am  # After 6pm
        )

        if is_off_hours and event.event_type in [
            AuditEventType.ASSET_REGISTERED,
            AuditEventType.ASSET_UPDATED,
            AuditEventType.POLICY_CREATED,
            AuditEventType.POLICY_UPDATED,
        ]:
            anomaly_id = f"anomaly-{uuid.uuid4()}"
            anomaly = Anomaly(
                anomaly_id=anomaly_id,
                anomaly_type=AnomalyType.OFF_HOURS_ACCESS,
                detected_at=datetime.utcnow(),
                description=f"Off-hours {event.event_type.value} by {event.actor}",
                severity="low",
                affected_events=[event.event_id],
                affected_assets=[event.asset_id] if event.asset_id else [],
                affected_users=[event.actor],
                metadata={
                    "hour": hour,
                    "weekday": weekday,
                },
            )
            self._anomalies[anomaly_id] = anomaly

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get audit statistics.

        Returns:
            Statistics about tracked events
        """
        total_events = len(self._events)

        # Count by type
        by_type = {}
        for event_type, event_ids in self._event_index["by_type"].items():
            by_type[event_type] = len(event_ids)

        # Count by result
        by_result = {}
        for result, event_ids in self._event_index["by_result"].items():
            by_result[result] = len(event_ids)

        # Recent activity (last 24 hours)
        recent_time = datetime.utcnow() - timedelta(hours=24)
        recent_events = [e for e in self._events.values() if e.timestamp >= recent_time]

        return {
            "total_events": total_events,
            "total_anomalies": len(self._anomalies),
            "by_type": by_type,
            "by_result": by_result,
            "recent_24h": len(recent_events),
            "unique_actors": len(self._event_index["by_actor"]),
            "unique_assets": len(self._event_index["by_asset"]),
        }

    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._events.clear()
        self._anomalies.clear()
        self._event_index = {
            "by_type": {},
            "by_actor": {},
            "by_asset": {},
            "by_result": {},
        }


# ============================================================================
# Singleton Access
# ============================================================================


def get_audit_monitor() -> AuditMonitor:
    """Get the singleton audit monitor instance."""
    return AuditMonitor()
