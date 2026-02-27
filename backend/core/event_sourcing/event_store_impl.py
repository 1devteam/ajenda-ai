"""
Event Sourcing Implementation for Omnipath v5.0
Complete event store with PostgreSQL backend and event replay

Built with Pride for Obex Blackvault
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy import Column, String, Integer, DateTime, Text, Index, select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from backend.core.logging_config import get_logger, LoggerMixin


logger = get_logger(__name__)
Base = declarative_base()

T = TypeVar('T', bound='Event')


# ============================================================================
# Event Models
# ============================================================================

class EventType(str, Enum):
    """Standard event types in the system"""
    
    # Agent events
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_ACTIVATED = "agent.activated"
    AGENT_DEACTIVATED = "agent.deactivated"
    
    # Mission events
    MISSION_CREATED = "mission.created"
    MISSION_STARTED = "mission.started"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"
    MISSION_CANCELLED = "mission.cancelled"
    
    # Economy events
    CREDIT_EARNED = "economy.credit_earned"
    CREDIT_SPENT = "economy.credit_spent"
    CREDIT_TRANSFERRED = "economy.credit_transferred"
    BALANCE_ADJUSTED = "economy.balance_adjusted"
    
    # Meta-learning events
    LEARNING_RECORDED = "meta.learning_recorded"
    PATTERN_DETECTED = "meta.pattern_detected"
    OPTIMIZATION_APPLIED = "meta.optimization_applied"
    
    # System events
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"
    SYSTEM_ERROR = "system.error"


@dataclass
class Event:
    """
    Base event class for all domain events
    """
    event_id: str
    event_type: str
    aggregate_id: str
    aggregate_type: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    version: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'aggregate_id': self.aggregate_id,
            'aggregate_type': self.aggregate_type,
            'data': self.data,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'version': self.version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary"""
        return cls(
            event_id=data['event_id'],
            event_type=data['event_type'],
            aggregate_id=data['aggregate_id'],
            aggregate_type=data['aggregate_type'],
            data=data['data'],
            metadata=data['metadata'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            version=data['version']
        )


class EventRecord(Base):
    """
    Database model for storing events
    """
    __tablename__ = 'event_store'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Event identification
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    
    # Aggregate identification
    aggregate_id = Column(String(36), nullable=False, index=True)
    aggregate_type = Column(String(50), nullable=False, index=True)
    
    # Event data
    data = Column(Text, nullable=False)  # JSON
    event_metadata = Column("metadata", Text, nullable=False)  # JSON
    
    # Versioning
    version = Column(Integer, nullable=False)
    
    # Timestamp
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_aggregate', 'aggregate_id', 'version'),
        Index('idx_type_time', 'event_type', 'timestamp'),
        Index('idx_aggregate_type_time', 'aggregate_type', 'timestamp'),
    )


# ============================================================================
# Event Store
# ============================================================================

class EventStore(LoggerMixin):
    """
    Event store implementation with PostgreSQL backend
    """
    
    def __init__(self, session: AsyncSession):
        """
        Initialize event store
        
        Args:
            session: Database session
        """
        self.session = session
    
    async def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None
    ) -> Event:
        """
        Append new event to the store
        
        Args:
            aggregate_id: ID of the aggregate
            aggregate_type: Type of the aggregate
            event_type: Type of event
            data: Event data
            metadata: Optional metadata
            expected_version: Expected current version (for optimistic locking)
        
        Returns:
            Created event
        
        Raises:
            ConcurrencyError: If expected_version doesn't match
        """
        # Get current version
        current_version = await self._get_current_version(aggregate_id)
        
        # Check optimistic locking
        if expected_version is not None and current_version != expected_version:
            raise ConcurrencyError(
                f"Version mismatch: expected {expected_version}, got {current_version}"
            )
        
        # Create event
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            data=data,
            metadata=metadata or {},
            timestamp=datetime.utcnow(),
            version=current_version + 1
        )
        
        # Save to database
        record = EventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            data=json.dumps(event.data),
            event_metadata=json.dumps(event.metadata),
            version=event.version,
            timestamp=event.timestamp
        )
        
        self.session.add(record)
        await self.session.commit()
        
        self.log_info(
            f"Event appended: {event_type}",
            event_id=event.event_id,
            aggregate_id=aggregate_id,
            version=event.version
        )
        
        return event
    
    async def get_events(
        self,
        aggregate_id: str,
        from_version: int = 0,
        to_version: Optional[int] = None
    ) -> List[Event]:
        """
        Get events for an aggregate
        
        Args:
            aggregate_id: ID of the aggregate
            from_version: Start version (inclusive)
            to_version: End version (inclusive, None for all)
        
        Returns:
            List of events
        """
        query = select(EventRecord).where(
            EventRecord.aggregate_id == aggregate_id,
            EventRecord.version >= from_version
        )
        
        if to_version is not None:
            query = query.where(EventRecord.version <= to_version)
        
        query = query.order_by(EventRecord.version)
        
        result = await self.session.execute(query)
        records = result.scalars().all()
        
        return [self._record_to_event(record) for record in records]
    
    async def get_events_by_type(
        self,
        event_type: str,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        Get events by type within time range
        
        Args:
            event_type: Type of events to retrieve
            from_time: Start time (inclusive)
            to_time: End time (inclusive)
            limit: Maximum number of events
        
        Returns:
            List of events
        """
        query = select(EventRecord).where(
            EventRecord.event_type == event_type
        )
        
        if from_time:
            query = query.where(EventRecord.timestamp >= from_time)
        
        if to_time:
            query = query.where(EventRecord.timestamp <= to_time)
        
        query = query.order_by(EventRecord.timestamp.desc()).limit(limit)
        
        result = await self.session.execute(query)
        records = result.scalars().all()
        
        return [self._record_to_event(record) for record in records]
    
    async def get_all_events(
        self,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Event]:
        """
        Get all events within time range
        
        Args:
            from_time: Start time (inclusive)
            to_time: End time (inclusive)
            limit: Maximum number of events
        
        Returns:
            List of events
        """
        query = select(EventRecord)
        
        if from_time:
            query = query.where(EventRecord.timestamp >= from_time)
        
        if to_time:
            query = query.where(EventRecord.timestamp <= to_time)
        
        query = query.order_by(EventRecord.timestamp.desc()).limit(limit)
        
        result = await self.session.execute(query)
        records = result.scalars().all()
        
        return [self._record_to_event(record) for record in records]
    
    async def replay_events(
        self,
        aggregate_id: str,
        handler: 'EventHandler'
    ) -> Any:
        """
        Replay events to rebuild aggregate state
        
        Args:
            aggregate_id: ID of the aggregate
            handler: Event handler to process events
        
        Returns:
            Rebuilt aggregate state
        """
        events = await self.get_events(aggregate_id)
        
        self.log_info(
            f"Replaying {len(events)} events",
            aggregate_id=aggregate_id
        )
        
        state = None
        for event in events:
            state = await handler.handle(event, state)
        
        return state
    
    async def _get_current_version(self, aggregate_id: str) -> int:
        """Get current version of aggregate"""
        query = select(EventRecord.version).where(
            EventRecord.aggregate_id == aggregate_id
        ).order_by(EventRecord.version.desc()).limit(1)
        
        result = await self.session.execute(query)
        version = result.scalar()
        
        return version if version is not None else 0
    
    @staticmethod
    def _record_to_event(record: EventRecord) -> Event:
        """Convert database record to event"""
        return Event(
            event_id=record.event_id,
            event_type=record.event_type,
            aggregate_id=record.aggregate_id,
            aggregate_type=record.aggregate_type,
            data=json.loads(record.data),
            metadata=json.loads(record.event_metadata),
            timestamp=record.timestamp,
            version=record.version
        )


# ============================================================================
# Event Handler
# ============================================================================

class EventHandler:
    """
    Base class for event handlers
    """
    
    async def handle(self, event: Event, state: Any) -> Any:
        """
        Handle event and update state
        
        Args:
            event: Event to handle
            state: Current state
        
        Returns:
            Updated state
        """
        handler_name = f"on_{event.event_type.replace('.', '_')}"
        handler = getattr(self, handler_name, None)
        
        if handler:
            return await handler(event, state)
        
        return state


# ============================================================================
# Exceptions
# ============================================================================

class ConcurrencyError(Exception):
    """Raised when optimistic locking fails"""
    pass


class EventStoreError(Exception):
    """Base exception for event store errors"""
    pass


# ============================================================================
# Event Projections
# ============================================================================

class Projection(LoggerMixin):
    """
    Base class for event projections (read models)
    """
    
    def __init__(self, event_store: EventStore):
        """
        Initialize projection
        
        Args:
            event_store: Event store to read from
        """
        self.event_store = event_store
    
    async def rebuild(self) -> None:
        """Rebuild projection from all events"""
        raise NotImplementedError
    
    async def handle_event(self, event: Event) -> None:
        """Handle single event"""
        raise NotImplementedError


# ============================================================================
# Snapshot Support
# ============================================================================

@dataclass
class Snapshot:
    """
    Snapshot of aggregate state at a specific version
    """
    aggregate_id: str
    aggregate_type: str
    version: int
    state: Dict[str, Any]
    timestamp: datetime


class SnapshotRecord(Base):
    """
    Database model for aggregate snapshots.
    Maps to the ``snapshot_store`` table created by migration e1776d23c66e.
    """
    __tablename__ = 'snapshot_store'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    aggregate_id   = Column(String(36), nullable=False, index=True)
    aggregate_type = Column(String(50), nullable=False)
    version        = Column(Integer, nullable=False)
    state          = Column(Text, nullable=False)   # JSON
    timestamp      = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_snapshot_agg_ver', 'aggregate_id', 'version'),
    )


class SnapshotStore(LoggerMixin):
    """
    PostgreSQL-backed store for aggregate snapshots.

    Snapshots allow event replay to start from a known state rather than
    replaying the entire event history, which is critical for aggregates
    with long histories.
    """

    # Take a snapshot every N events to bound replay cost.
    SNAPSHOT_THRESHOLD: int = 50

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: Async SQLAlchemy session.
        """
        self.session = session

    async def save_snapshot(
        self,
        aggregate_id: str,
        aggregate_type: str,
        version: int,
        state: Dict[str, Any],
    ) -> Snapshot:
        """
        Persist a snapshot of aggregate state at the given version.

        If a snapshot already exists for this aggregate at this version it is
        replaced (idempotent upsert via delete + insert).

        Args:
            aggregate_id:   Unique aggregate identifier.
            aggregate_type: Aggregate type name (e.g. ``"agent"``).
            version:        Event version at which the snapshot was taken.
            state:          Full aggregate state as a JSON-serialisable dict.

        Returns:
            The persisted :class:`Snapshot` dataclass.
        """
        now = datetime.utcnow()

        # Delete any existing snapshot for this aggregate at this version
        # (idempotent — safe to call multiple times).
        existing_q = select(SnapshotRecord).where(
            SnapshotRecord.aggregate_id == aggregate_id,
            SnapshotRecord.version == version,
        )
        result = await self.session.execute(existing_q)
        existing = result.scalar_one_or_none()
        if existing:
            await self.session.delete(existing)

        record = SnapshotRecord(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            version=version,
            state=json.dumps(state),
            timestamp=now,
        )
        self.session.add(record)
        await self.session.commit()

        self.log_info(
            "Snapshot saved",
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            version=version,
        )

        return Snapshot(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            version=version,
            state=state,
            timestamp=now,
        )

    async def get_snapshot(self, aggregate_id: str) -> Optional[Snapshot]:
        """
        Retrieve the most recent snapshot for an aggregate.

        Args:
            aggregate_id: Unique aggregate identifier.

        Returns:
            The latest :class:`Snapshot`, or ``None`` if no snapshot exists.
        """
        query = (
            select(SnapshotRecord)
            .where(SnapshotRecord.aggregate_id == aggregate_id)
            .order_by(desc(SnapshotRecord.version))
            .limit(1)
        )
        result = await self.session.execute(query)
        record = result.scalar_one_or_none()

        if record is None:
            return None

        return Snapshot(
            aggregate_id=record.aggregate_id,
            aggregate_type=record.aggregate_type,
            version=record.version,
            state=json.loads(record.state),
            timestamp=record.timestamp,
        )

    async def should_snapshot(
        self,
        aggregate_id: str,
        current_version: int,
    ) -> bool:
        """
        Return ``True`` when a new snapshot should be taken.

        A snapshot is due when the number of events since the last snapshot
        exceeds :attr:`SNAPSHOT_THRESHOLD`.

        Args:
            aggregate_id:    Aggregate to check.
            current_version: Latest event version for the aggregate.

        Returns:
            ``True`` if a snapshot should be taken, ``False`` otherwise.
        """
        latest = await self.get_snapshot(aggregate_id)
        last_snapshot_version = latest.version if latest else 0
        events_since = current_version - last_snapshot_version
        return events_since >= self.SNAPSHOT_THRESHOLD
