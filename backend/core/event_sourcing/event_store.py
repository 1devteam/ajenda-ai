"""
Event Sourcing — Production Implementation
Omnipath v5.0

This module is the public API for event sourcing. All classes are fully
implemented in event_store_impl.py and re-exported here for backwards
compatibility with any code that imports from this module directly.

Built with Pride for Obex Blackvault
"""

# Re-export everything from the full implementation so that any existing
# import of `from backend.core.event_sourcing.event_store import EventStore`
# continues to work without modification.
from backend.core.event_sourcing.event_store_impl import (  # noqa: F401
    Event,
    EventType,
    EventRecord,
    EventStore,
    EventHandler,
    ConcurrencyError,
    EventStoreError,
    Projection,
    Snapshot,
    SnapshotStore,
)

# ---------------------------------------------------------------------------
# EventSourcedAggregate — production implementation
# ---------------------------------------------------------------------------
# The stub version held events only in memory. This version integrates with
# the persistent EventStore so that uncommitted events can be flushed to the
# database by calling `save_uncommitted_events(event_store)`.

from typing import List, Optional
import uuid


class EventSourcedAggregate:
    """
    Production event-sourced aggregate base class.

    Usage::

        class AgentAggregate(EventSourcedAggregate):
            def __init__(self, agent_id: str):
                super().__init__(aggregate_id=agent_id, aggregate_type="agent")
                self.name: Optional[str] = None

            def on_agent_created(self, event: Event) -> None:
                self.name = event.data["name"]

        # Rebuild from history
        agg = AgentAggregate(agent_id)
        events = await event_store.get_events(agent_id)
        agg.load_from_history(events)

        # Apply new event
        agg.apply("agent.updated", {"name": "new_name"})
        await agg.save_uncommitted_events(event_store)
    """

    def __init__(
        self,
        aggregate_id: Optional[str] = None,
        aggregate_type: str = "aggregate",
    ) -> None:
        self.aggregate_id: str = aggregate_id or str(uuid.uuid4())
        self.aggregate_type: str = aggregate_type
        self.version: int = 0
        self._uncommitted_events: List[Event] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self, event_type: str, data: dict, metadata: Optional[dict] = None
    ) -> None:
        """
        Record a new domain event and update local state.

        The event is held in `_uncommitted_events` until
        `save_uncommitted_events` is called.
        """
        from datetime import datetime

        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            data=data,
            metadata=metadata or {},
            timestamp=datetime.utcnow(),
            version=self.version + 1,
        )
        self.version += 1
        self._uncommitted_events.append(event)
        self._dispatch(event)

    def load_from_history(self, events: List[Event]) -> None:
        """
        Rebuild aggregate state by replaying a list of persisted events.
        Clears any uncommitted events first.
        """
        self._uncommitted_events.clear()
        for event in events:
            self.version = event.version
            self._dispatch(event)

    def get_uncommitted_events(self) -> List[Event]:
        """Return events that have not yet been persisted."""
        return list(self._uncommitted_events)

    def mark_events_as_committed(self) -> None:
        """Clear the uncommitted event buffer after successful persistence."""
        self._uncommitted_events.clear()

    async def save_uncommitted_events(self, event_store: "EventStore") -> None:
        """
        Persist all uncommitted events to the event store and clear the buffer.

        Args:
            event_store: The EventStore instance to write to.
        """
        for event in self._uncommitted_events:
            await event_store.append(
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                event_type=event.event_type,
                data=event.data,
                metadata=event.metadata,
                expected_version=event.version - 1 if event.version > 1 else None,
            )
        self.mark_events_as_committed()

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, event: Event) -> None:
        """
        Dispatch event to a typed handler method if one exists.

        The handler method name is derived from the event type by replacing
        dots with underscores and prepending ``on_``.
        Example: ``agent.created`` → ``on_agent_created``
        """
        handler_name = "on_" + event.event_type.replace(".", "_")
        handler = getattr(self, handler_name, None)
        if callable(handler):
            handler(event)


__all__ = [
    "Event",
    "EventType",
    "EventRecord",
    "EventStore",
    "EventHandler",
    "ConcurrencyError",
    "EventStoreError",
    "Projection",
    "Snapshot",
    "SnapshotStore",
    "EventSourcedAggregate",
]
