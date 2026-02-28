"""
Lineage Repository
Database operations for asset lineage tracking

Built with Pride for Obex Blackvault
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta

from backend.database.governance_models import GovernanceLineageEvent
from backend.database.repositories.base import BaseRepository


class LineageRepository(BaseRepository[GovernanceLineageEvent]):
    """Repository for lineage event operations"""

    def __init__(self, db: Session):
        super().__init__(db, GovernanceLineageEvent)

    def create_event(
        self,
        id: str,
        asset_id: str,
        event_type: str,
        actor_id: str,
        event_data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> GovernanceLineageEvent:
        """
        Create lineage event

        Args:
            id: Event ID
            asset_id: Asset ID
            event_type: Type of event (created, updated, deployed, etc.)
            actor_id: User or system that triggered event
            event_data: Optional event data
            timestamp: Optional timestamp (defaults to now)

        Returns:
            Created GovernanceLineageEvent instance
        """
        return self.create(
            id=id,
            asset_id=asset_id,
            event_type=event_type,
            actor_id=actor_id,
            event_data=event_data or {},
            timestamp=timestamp or datetime.utcnow(),
        )

    def get_asset_history(
        self,
        asset_id: str,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceLineageEvent]:
        """
        Get lineage history for asset

        Args:
            asset_id: Asset ID
            event_type: Optional event type filter
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceLineageEvent instances
        """
        query = self.db.query(GovernanceLineageEvent).filter(
            GovernanceLineageEvent.asset_id == asset_id
        )

        if event_type:
            query = query.filter(GovernanceLineageEvent.event_type == event_type)

        return (
            query.order_by(desc(GovernanceLineageEvent.timestamp)).limit(limit).offset(offset).all()
        )

    def get_by_actor(
        self, actor_id: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceLineageEvent]:
        """
        Get events by actor

        Args:
            actor_id: Actor ID
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceLineageEvent instances
        """
        return (
            self.db.query(GovernanceLineageEvent)
            .filter(GovernanceLineageEvent.actor_id == actor_id)
            .order_by(desc(GovernanceLineageEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_event_type(
        self, event_type: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceLineageEvent]:
        """
        Get events by type

        Args:
            event_type: Event type
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceLineageEvent instances
        """
        return (
            self.db.query(GovernanceLineageEvent)
            .filter(GovernanceLineageEvent.event_type == event_type)
            .order_by(desc(GovernanceLineageEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_recent_events(self, hours: int = 24, limit: int = 100) -> List[GovernanceLineageEvent]:
        """
        Get recent events within time window

        Args:
            hours: Number of hours to look back
            limit: Maximum results

        Returns:
            List of GovernanceLineageEvent instances
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(GovernanceLineageEvent)
            .filter(GovernanceLineageEvent.timestamp >= cutoff)
            .order_by(desc(GovernanceLineageEvent.timestamp))
            .limit(limit)
            .all()
        )

    def get_event_timeline(
        self,
        asset_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[GovernanceLineageEvent]:
        """
        Get event timeline for asset within date range

        Args:
            asset_id: Asset ID
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            List of GovernanceLineageEvent instances
        """
        query = self.db.query(GovernanceLineageEvent).filter(
            GovernanceLineageEvent.asset_id == asset_id
        )

        if start_date:
            query = query.filter(GovernanceLineageEvent.timestamp >= start_date)

        if end_date:
            query = query.filter(GovernanceLineageEvent.timestamp <= end_date)

        return query.order_by(GovernanceLineageEvent.timestamp).all()

    def count_events_by_type(
        self, asset_id: Optional[str] = None, hours: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Count events by type

        Args:
            asset_id: Optional asset ID filter
            hours: Optional time window in hours

        Returns:
            Dictionary mapping event types to counts
        """
        query = self.db.query(
            GovernanceLineageEvent.event_type,
            self.db.func.count(GovernanceLineageEvent.id),
        )

        if asset_id:
            query = query.filter(GovernanceLineageEvent.asset_id == asset_id)

        if hours:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            query = query.filter(GovernanceLineageEvent.timestamp >= cutoff)

        results = query.group_by(GovernanceLineageEvent.event_type).all()
        return {event_type: count for event_type, count in results}
