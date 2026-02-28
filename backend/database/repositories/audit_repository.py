"""
Audit Repository
Database operations for governance audit events

Built with Pride for Obex Blackvault
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from datetime import datetime, timedelta

from backend.database.governance_models import GovernanceAuditEvent
from backend.database.repositories.base import BaseRepository


class AuditRepository(BaseRepository[GovernanceAuditEvent]):
    """Repository for audit event operations"""

    def __init__(self, db: Session):
        super().__init__(db, GovernanceAuditEvent)

    def create_event(
        self,
        id: str,
        tenant_id: str,
        event_type: str,
        event_category: str,
        severity: str,
        actor_id: str,
        actor_type: str,
        outcome: str,
        asset_id: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> GovernanceAuditEvent:
        """
        Create audit event

        Args:
            id: Event ID
            tenant_id: Tenant ID
            event_type: Event type
            event_category: Event category (access, modification, compliance, etc.)
            severity: Severity (info, warning, error, critical)
            actor_id: Actor ID
            actor_type: Actor type (user, agent, system)
            outcome: Outcome (success, failure, blocked)
            asset_id: Optional asset ID
            event_data: Optional event data
            ip_address: Optional IP address
            user_agent: Optional user agent

        Returns:
            Created GovernanceAuditEvent instance
        """
        return self.create(
            id=id,
            tenant_id=tenant_id,
            asset_id=asset_id,
            event_type=event_type,
            event_category=event_category,
            severity=severity,
            actor_id=actor_id,
            actor_type=actor_type,
            event_data=event_data or {},
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def get_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAuditEvent]:
        """
        Get audit events for tenant

        Args:
            tenant_id: Tenant ID
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(GovernanceAuditEvent.tenant_id == tenant_id)
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_asset(
        self, asset_id: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAuditEvent]:
        """
        Get audit events for asset

        Args:
            asset_id: Asset ID
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(GovernanceAuditEvent.asset_id == asset_id)
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_actor(
        self, actor_id: str, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAuditEvent]:
        """
        Get audit events by actor

        Args:
            actor_id: Actor ID
            tenant_id: Tenant ID
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.actor_id == actor_id,
                    GovernanceAuditEvent.tenant_id == tenant_id,
                )
            )
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_severity(
        self, tenant_id: str, severity: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAuditEvent]:
        """
        Get audit events by severity

        Args:
            tenant_id: Tenant ID
            severity: Severity level
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.severity == severity,
                )
            )
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_category(
        self, tenant_id: str, category: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAuditEvent]:
        """
        Get audit events by category

        Args:
            tenant_id: Tenant ID
            category: Event category
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.event_category == category,
                )
            )
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_failed_events(
        self, tenant_id: str, hours: int = 24, limit: int = 100
    ) -> List[GovernanceAuditEvent]:
        """
        Get failed events within time window

        Args:
            tenant_id: Tenant ID
            hours: Number of hours to look back
            limit: Maximum results

        Returns:
            List of failed GovernanceAuditEvent instances
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.outcome.in_(["failure", "blocked"]),
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .all()
        )

    def get_critical_events(
        self, tenant_id: str, hours: int = 24, limit: int = 100
    ) -> List[GovernanceAuditEvent]:
        """
        Get critical events within time window

        Args:
            tenant_id: Tenant ID
            hours: Number of hours to look back
            limit: Maximum results

        Returns:
            List of critical GovernanceAuditEvent instances
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.severity == "critical",
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .order_by(desc(GovernanceAuditEvent.timestamp))
            .limit(limit)
            .all()
        )

    def search_events(
        self,
        tenant_id: str,
        event_type: Optional[str] = None,
        event_category: Optional[str] = None,
        severity: Optional[str] = None,
        actor_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        outcome: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceAuditEvent]:
        """
        Search audit events with multiple filters

        Args:
            tenant_id: Tenant ID
            event_type: Optional event type filter
            event_category: Optional category filter
            severity: Optional severity filter
            actor_id: Optional actor filter
            asset_id: Optional asset filter
            outcome: Optional outcome filter
            start_date: Optional start date
            end_date: Optional end date
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAuditEvent instances
        """
        query = self.db.query(GovernanceAuditEvent).filter(
            GovernanceAuditEvent.tenant_id == tenant_id
        )

        if event_type:
            query = query.filter(GovernanceAuditEvent.event_type == event_type)

        if event_category:
            query = query.filter(GovernanceAuditEvent.event_category == event_category)

        if severity:
            query = query.filter(GovernanceAuditEvent.severity == severity)

        if actor_id:
            query = query.filter(GovernanceAuditEvent.actor_id == actor_id)

        if asset_id:
            query = query.filter(GovernanceAuditEvent.asset_id == asset_id)

        if outcome:
            query = query.filter(GovernanceAuditEvent.outcome == outcome)

        if start_date:
            query = query.filter(GovernanceAuditEvent.timestamp >= start_date)

        if end_date:
            query = query.filter(GovernanceAuditEvent.timestamp <= end_date)

        return (
            query.order_by(desc(GovernanceAuditEvent.timestamp)).limit(limit).offset(offset).all()
        )

    def get_statistics(self, tenant_id: str, hours: int = 24) -> Dict[str, Any]:
        """
        Get audit statistics for tenant

        Args:
            tenant_id: Tenant ID
            hours: Time window in hours

        Returns:
            Dictionary with statistics
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Total events
        total = (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .count()
        )

        # By severity
        by_severity = {}
        severity_counts = (
            self.db.query(GovernanceAuditEvent.severity, func.count(GovernanceAuditEvent.id))
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .group_by(GovernanceAuditEvent.severity)
            .all()
        )

        for severity, count in severity_counts:
            by_severity[severity] = count

        # By outcome
        by_outcome = {}
        outcome_counts = (
            self.db.query(GovernanceAuditEvent.outcome, func.count(GovernanceAuditEvent.id))
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .group_by(GovernanceAuditEvent.outcome)
            .all()
        )

        for outcome, count in outcome_counts:
            by_outcome[outcome] = count

        # By category
        by_category = {}
        category_counts = (
            self.db.query(GovernanceAuditEvent.event_category, func.count(GovernanceAuditEvent.id))
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .group_by(GovernanceAuditEvent.event_category)
            .all()
        )

        for category, count in category_counts:
            by_category[category] = count

        return {
            "total": total,
            "by_severity": by_severity,
            "by_outcome": by_outcome,
            "by_category": by_category,
            "time_window_hours": hours,
        }

    def detect_anomalies(
        self, tenant_id: str, actor_id: str, hours: int = 1, threshold: int = 100
    ) -> bool:
        """
        Detect anomalous activity (simple threshold-based)

        Args:
            tenant_id: Tenant ID
            actor_id: Actor ID to check
            hours: Time window in hours
            threshold: Event count threshold

        Returns:
            True if anomaly detected
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        count = (
            self.db.query(GovernanceAuditEvent)
            .filter(
                and_(
                    GovernanceAuditEvent.tenant_id == tenant_id,
                    GovernanceAuditEvent.actor_id == actor_id,
                    GovernanceAuditEvent.timestamp >= cutoff,
                )
            )
            .count()
        )

        return count > threshold
