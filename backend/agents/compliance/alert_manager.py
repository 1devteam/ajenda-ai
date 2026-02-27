"""
Alert Manager - Notification and alerting system.

Sends notifications for compliance violations, escalates critical issues,
manages alert rules and recipients, tracks acknowledgments.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid


# ============================================================================
# Enums
# ============================================================================

class AlertType(Enum):
    """Types of alerts."""
    POLICY_VIOLATION = "policy_violation"
    COMPLIANCE_FAILURE = "compliance_failure"
    ANOMALY_DETECTED = "anomaly_detected"
    APPROVAL_REQUIRED = "approval_required"
    AUDIT_GAP = "audit_gap"
    RISK_THRESHOLD = "risk_threshold"
    SYSTEM_ERROR = "system_error"


class AlertStatus(Enum):
    """Status of an alert."""
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class AlertSeverity(Enum):
    """Severity of an alert."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class Alert:
    """
    Represents an alert notification.
    """
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    timestamp: datetime
    title: str
    description: str
    affected_assets: List[str]
    recipients: List[str]
    status: AlertStatus
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "title": self.title,
            "description": self.description,
            "affected_assets": self.affected_assets,
            "recipients": self.recipients,
            "status": self.status.value,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
            "metadata": self.metadata,
        }


@dataclass
class AlertRule:
    """
    Defines when to send alerts.
    """
    rule_id: str
    name: str
    alert_type: AlertType
    conditions: Dict[str, Any]  # Conditions that trigger alert
    recipients: List[str]  # User IDs or email addresses
    severity: AlertSeverity
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Alert Manager
# ============================================================================

class AlertManager:
    """
    Manages alert notifications and escalations.
    
    Sends notifications, tracks acknowledgments, manages alert rules.
    Singleton pattern ensures consistent alerting.
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
        
        self._alerts: Dict[str, Alert] = {}
        self._rules: Dict[str, AlertRule] = {}
        self._initialize_default_rules()
        self._initialized = True
    
    def _initialize_default_rules(self) -> None:
        """Initialize default alert rules."""
        # Critical policy violations
        self.add_rule(AlertRule(
            rule_id="rule-policy-violation-critical",
            name="Critical Policy Violation",
            alert_type=AlertType.POLICY_VIOLATION,
            conditions={"severity": "critical"},
            recipients=["compliance-team", "security-team"],
            severity=AlertSeverity.CRITICAL,
        ))
        
        # Compliance failures
        self.add_rule(AlertRule(
            rule_id="rule-compliance-failure",
            name="Compliance Check Failure",
            alert_type=AlertType.COMPLIANCE_FAILURE,
            conditions={"status": "fail"},
            recipients=["compliance-team"],
            severity=AlertSeverity.HIGH,
        ))
        
        # Anomalies
        self.add_rule(AlertRule(
            rule_id="rule-anomaly-high",
            name="High Severity Anomaly",
            alert_type=AlertType.ANOMALY_DETECTED,
            conditions={"severity": ["high", "critical"]},
            recipients=["security-team"],
            severity=AlertSeverity.HIGH,
        ))
        
        # High-risk approvals
        self.add_rule(AlertRule(
            rule_id="rule-high-risk-approval",
            name="High Risk Approval Required",
            alert_type=AlertType.APPROVAL_REQUIRED,
            conditions={"risk_tier": ["high", "critical"]},
            recipients=["compliance-officer"],
            severity=AlertSeverity.HIGH,
        ))
    
    def send_alert(self, alert: Alert) -> None:
        """
        Send an alert notification.
        
        Args:
            alert: Alert to send
        """
        # Store alert
        self._alerts[alert.alert_id] = alert
        
        # Update status to sent
        alert.status = AlertStatus.SENT
        
        # In production, this would:
        # - Send email notifications
        # - Send Slack/Teams messages
        # - Trigger webhooks
        # - Create tickets in issue tracking systems
        
        # For now, just log
        print(f"[ALERT] {alert.severity.value.upper()}: {alert.title}")
        print(f"  Recipients: {', '.join(alert.recipients)}")
        print(f"  Description: {alert.description}")
    
    def create_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        description: str,
        affected_assets: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Alert:
        """
        Create and send an alert.
        
        Args:
            alert_type: Type of alert
            severity: Severity level
            title: Alert title
            description: Alert description
            affected_assets: List of affected asset IDs
            metadata: Additional metadata
            
        Returns:
            Created alert
        """
        # Find matching rules to determine recipients
        recipients = self._get_recipients_for_alert(alert_type, severity, metadata or {})
        
        alert = Alert(
            alert_id=f"alert-{uuid.uuid4()}",
            alert_type=alert_type,
            severity=severity,
            timestamp=datetime.utcnow(),
            title=title,
            description=description,
            affected_assets=affected_assets,
            recipients=recipients,
            status=AlertStatus.PENDING,
            metadata=metadata or {},
        )
        
        self.send_alert(alert)
        return alert
    
    def _get_recipients_for_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        metadata: Dict[str, Any],
    ) -> List[str]:
        """Get recipients for an alert based on rules."""
        recipients = set()
        
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            
            if rule.alert_type != alert_type:
                continue
            
            # Check if conditions match
            matches = True
            for key, value in rule.conditions.items():
                if key == "severity":
                    if isinstance(value, list):
                        if severity.value not in value:
                            matches = False
                    elif severity.value != value:
                        matches = False
                elif key in metadata:
                    if isinstance(value, list):
                        if metadata[key] not in value:
                            matches = False
                    elif metadata[key] != value:
                        matches = False
            
            if matches:
                recipients.update(rule.recipients)
        
        return list(recipients) if recipients else ["default-admin"]
    
    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """
        Acknowledge an alert.
        
        Args:
            alert_id: Alert ID
            user: User acknowledging
            
        Returns:
            True if successful
        """
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = user
        alert.acknowledged_at = datetime.utcnow()
        return True
    
    def resolve_alert(self, alert_id: str, user: str, resolution: str) -> bool:
        """
        Resolve an alert.
        
        Args:
            alert_id: Alert ID
            user: User resolving
            resolution: Resolution description
            
        Returns:
            True if successful
        """
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        
        alert.status = AlertStatus.RESOLVED
        alert.resolved_by = user
        alert.resolved_at = datetime.utcnow()
        alert.resolution = resolution
        return True
    
    def escalate_alert(self, alert_id: str) -> bool:
        """
        Escalate an alert to higher severity.
        
        Args:
            alert_id: Alert ID
            
        Returns:
            True if successful
        """
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        
        # Increase severity
        if alert.severity == AlertSeverity.LOW:
            alert.severity = AlertSeverity.MEDIUM
        elif alert.severity == AlertSeverity.MEDIUM:
            alert.severity = AlertSeverity.HIGH
        elif alert.severity == AlertSeverity.HIGH:
            alert.severity = AlertSeverity.CRITICAL
        
        alert.status = AlertStatus.ESCALATED
        
        # Resend with higher severity
        self.send_alert(alert)
        return True
    
    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get alert by ID."""
        return self._alerts.get(alert_id)
    
    def get_active_alerts(self) -> List[Alert]:
        """
        Get all unresolved alerts.
        
        Returns:
            List of active alerts
        """
        return [
            alert for alert in self._alerts.values()
            if alert.status not in [AlertStatus.RESOLVED]
        ]
    
    def list_alerts(
        self,
        alert_type: Optional[AlertType] = None,
        severity: Optional[AlertSeverity] = None,
        status: Optional[AlertStatus] = None,
        limit: int = 100,
    ) -> List[Alert]:
        """
        List alerts with filters.
        
        Args:
            alert_type: Filter by type
            severity: Filter by severity
            status: Filter by status
            limit: Maximum number of alerts
            
        Returns:
            List of alerts
        """
        alerts = list(self._alerts.values())
        
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if status:
            alerts = [a for a in alerts if a.status == status]
        
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts[:limit]
    
    def add_rule(self, rule: AlertRule) -> None:
        """
        Add an alert rule.
        
        Args:
            rule: Alert rule
        """
        self._rules[rule.rule_id] = rule
    
    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove an alert rule.
        
        Args:
            rule_id: Rule ID
            
        Returns:
            True if removed
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False
    
    def list_rules(self) -> List[AlertRule]:
        """List all alert rules."""
        return list(self._rules.values())
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get alert statistics.
        
        Returns:
            Statistics about alerts
        """
        alerts = list(self._alerts.values())
        
        by_type = {}
        for alert_type in AlertType:
            by_type[alert_type.value] = len([
                a for a in alerts if a.alert_type == alert_type
            ])
        
        by_severity = {}
        for severity in AlertSeverity:
            by_severity[severity.value] = len([
                a for a in alerts if a.severity == severity
            ])
        
        by_status = {}
        for status in AlertStatus:
            by_status[status.value] = len([
                a for a in alerts if a.status == status
            ])
        
        return {
            "total_alerts": len(alerts),
            "active_alerts": len(self.get_active_alerts()),
            "by_type": by_type,
            "by_severity": by_severity,
            "by_status": by_status,
            "total_rules": len(self._rules),
        }
    
    def clear(self) -> None:
        """Clear all alerts (for testing)."""
        self._alerts.clear()
        self._rules.clear()
        self._initialize_default_rules()


# ============================================================================
# Singleton Access
# ============================================================================

def get_alert_manager() -> AlertManager:
    """Get the singleton alert manager instance."""
    return AlertManager()
