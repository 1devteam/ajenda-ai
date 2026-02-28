"""
Event Sourcing Projections — Omnipath v5.0

Concrete Projection subclasses that maintain denormalised read-model state by
processing domain events as they arrive.  Each projection:

  * implements ``handle_event`` to apply a single event incrementally
  * implements ``rebuild`` to replay the full event history from scratch
  * exposes typed query methods so callers never touch raw dicts

Three projections are provided:

  AgentProjection    — agent identity, status, and credit balance
  MissionProjection  — mission lifecycle and outcome data
  EconomyProjection  — per-agent credit ledger and balance

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.core.event_sourcing.event_store_impl import Event, EventStore, Projection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentProjection
# ---------------------------------------------------------------------------

class AgentProjection(Projection):
    """
    Maintains a denormalised, in-memory view of all agents.

    State is keyed by ``agent_id`` and updated incrementally as events arrive.
    The projection handles:

    * ``agent.created``   — initialise agent record
    * ``agent.updated``   — apply partial field updates
    * ``agent.deleted``   — mark agent as deleted
    * ``agent.activated`` / ``agent.deactivated`` — status transitions
    * ``economy.balance_adjusted`` — credit balance changes
    """

    def __init__(self, event_store: EventStore) -> None:
        super().__init__(event_store)
        # agent_id → state dict
        self._agents: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Projection interface
    # ------------------------------------------------------------------

    async def rebuild(self) -> None:
        """
        Replay all agent and economy events to rebuild the projection from
        scratch.  Safe to call multiple times (idempotent).
        """
        logger.info("AgentProjection.rebuild() started")
        self._agents.clear()

        events = await self.event_store.get_all_events()
        agent_event_types = {
            "agent.created",
            "agent.updated",
            "agent.deleted",
            "agent.activated",
            "agent.deactivated",
            "economy.balance_adjusted",
        }
        relevant = [e for e in events if e.event_type in agent_event_types]
        # Process in chronological order
        for event in sorted(relevant, key=lambda e: (e.timestamp, e.version)):
            await self.handle_event(event)

        logger.info(
            "AgentProjection.rebuild() complete — %d agent(s) loaded",
            len(self._agents),
        )

    async def handle_event(self, event: Event) -> None:
        """Apply a single event to the projection state."""
        handler_name = "_on_" + event.event_type.replace(".", "_")
        handler = getattr(self, handler_name, None)
        if handler is not None:
            handler(event)
        else:
            logger.debug(
                "AgentProjection: no handler for event type '%s'", event.event_type
            )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return the current state for *agent_id*, or ``None`` if unknown."""
        return self._agents.get(agent_id)

    def list_by_tenant(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return all non-deleted agents belonging to *tenant_id*."""
        results = [
            a
            for a in self._agents.values()
            if a.get("tenant_id") == tenant_id and not a.get("deleted", False)
        ]
        return results[offset : offset + limit]

    def get_balance(self, agent_id: str) -> float:
        """Return the current credit balance for *agent_id* (0.0 if unknown)."""
        agent = self._agents.get(agent_id)
        return float(agent.get("credit_balance", 0.0)) if agent else 0.0

    # ------------------------------------------------------------------
    # Event handlers (private)
    # ------------------------------------------------------------------

    def _on_agent_created(self, event: Event) -> None:
        self._agents[event.aggregate_id] = {
            "id": event.aggregate_id,
            "tenant_id": event.data.get("tenant_id"),
            "name": event.data.get("name"),
            "model": event.data.get("model"),
            "capabilities": event.data.get("capabilities", []),
            "system_prompt": event.data.get("system_prompt"),
            "temperature": event.data.get("temperature", 0.7),
            "status": "active",
            "credit_balance": 1000.0,  # default; adjusted by economy events
            "created_at": event.timestamp.isoformat(),
            "version": event.version,
            "deleted": False,
        }

    def _on_agent_updated(self, event: Event) -> None:
        agent = self._agents.get(event.aggregate_id)
        if agent is None:
            logger.warning(
                "AgentProjection: agent.updated for unknown agent '%s'",
                event.aggregate_id,
            )
            return
        # Apply only the fields present in the event payload
        for field_name, value in event.data.items():
            agent[field_name] = value
        agent["version"] = event.version

    def _on_agent_deleted(self, event: Event) -> None:
        agent = self._agents.get(event.aggregate_id)
        if agent is not None:
            agent["deleted"] = True
            agent["status"] = "deleted"
            agent["version"] = event.version

    def _on_agent_activated(self, event: Event) -> None:
        agent = self._agents.get(event.aggregate_id)
        if agent is not None:
            agent["status"] = "active"
            agent["version"] = event.version

    def _on_agent_deactivated(self, event: Event) -> None:
        agent = self._agents.get(event.aggregate_id)
        if agent is not None:
            agent["status"] = "inactive"
            agent["version"] = event.version

    def _on_economy_balance_adjusted(self, event: Event) -> None:
        agent = self._agents.get(event.aggregate_id)
        if agent is not None:
            current = float(agent.get("credit_balance", 0.0))
            delta = float(event.data.get("amount", 0.0))
            agent["credit_balance"] = current + delta
            agent["version"] = event.version


# ---------------------------------------------------------------------------
# MissionProjection
# ---------------------------------------------------------------------------

class MissionProjection(Projection):
    """
    Maintains a denormalised, in-memory view of all missions.

    Handles:

    * ``mission.created``   — initialise mission record
    * ``mission.started``   — record start time and running status
    * ``mission.completed`` — record result, cost, and tokens
    * ``mission.failed``    — record error and failed status
    * ``mission.cancelled`` — mark as cancelled
    """

    def __init__(self, event_store: EventStore) -> None:
        super().__init__(event_store)
        # mission_id → state dict
        self._missions: Dict[str, Dict[str, Any]] = {}
        # agent_id → list of mission_ids (for fast lookup by agent)
        self._by_agent: Dict[str, List[str]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Projection interface
    # ------------------------------------------------------------------

    async def rebuild(self) -> None:
        """Replay all mission events to rebuild the projection."""
        logger.info("MissionProjection.rebuild() started")
        self._missions.clear()
        self._by_agent.clear()

        events = await self.event_store.get_all_events()
        mission_event_types = {
            "mission.created",
            "mission.started",
            "mission.completed",
            "mission.failed",
            "mission.cancelled",
        }
        relevant = [e for e in events if e.event_type in mission_event_types]
        for event in sorted(relevant, key=lambda e: (e.timestamp, e.version)):
            await self.handle_event(event)

        logger.info(
            "MissionProjection.rebuild() complete — %d mission(s) loaded",
            len(self._missions),
        )

    async def handle_event(self, event: Event) -> None:
        """Apply a single event to the projection state."""
        handler_name = "_on_" + event.event_type.replace(".", "_")
        handler = getattr(self, handler_name, None)
        if handler is not None:
            handler(event)
        else:
            logger.debug(
                "MissionProjection: no handler for event type '%s'", event.event_type
            )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Return the current state for *mission_id*, or ``None`` if unknown."""
        return self._missions.get(mission_id)

    def list_by_agent(
        self,
        agent_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return missions for *agent_id*, optionally filtered by *status*."""
        mission_ids = self._by_agent.get(agent_id, [])
        missions = [
            self._missions[mid] for mid in mission_ids if mid in self._missions
        ]
        if status is not None:
            missions = [m for m in missions if m.get("status") == status]
        return missions[offset : offset + limit]

    def list_all(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return all missions, optionally filtered by *status*."""
        missions = list(self._missions.values())
        if status is not None:
            missions = [m for m in missions if m.get("status") == status]
        return missions[offset : offset + limit]

    # ------------------------------------------------------------------
    # Event handlers (private)
    # ------------------------------------------------------------------

    def _on_mission_created(self, event: Event) -> None:
        agent_id = event.data.get("agent_id")
        self._missions[event.aggregate_id] = {
            "id": event.aggregate_id,
            "agent_id": agent_id,
            "tenant_id": event.data.get("tenant_id"),
            "objective": event.data.get("objective") or event.data.get("command"),
            "status": "created",
            "priority": event.data.get("priority", "medium"),
            "context": event.data.get("context", {}),
            "result": None,
            "error": None,
            "tokens_used": 0,
            "cost": 0.0,
            "budget": event.data.get("budget"),
            "created_at": event.timestamp.isoformat(),
            "started_at": None,
            "completed_at": None,
            "version": event.version,
        }
        if agent_id:
            self._by_agent[agent_id].append(event.aggregate_id)

    def _on_mission_started(self, event: Event) -> None:
        mission = self._missions.get(event.aggregate_id)
        if mission is None:
            logger.warning(
                "MissionProjection: mission.started for unknown mission '%s'",
                event.aggregate_id,
            )
            return
        mission["status"] = "running"
        mission["started_at"] = event.timestamp.isoformat()
        mission["version"] = event.version

    def _on_mission_completed(self, event: Event) -> None:
        mission = self._missions.get(event.aggregate_id)
        if mission is None:
            return
        mission["status"] = "completed"
        mission["result"] = event.data.get("result")
        mission["tokens_used"] = event.data.get("tokens_used", 0)
        mission["cost"] = event.data.get("cost", 0.0)
        mission["completed_at"] = event.timestamp.isoformat()
        mission["version"] = event.version

    def _on_mission_failed(self, event: Event) -> None:
        mission = self._missions.get(event.aggregate_id)
        if mission is None:
            return
        mission["status"] = "failed"
        mission["error"] = event.data.get("error")
        mission["completed_at"] = event.timestamp.isoformat()
        mission["version"] = event.version

    def _on_mission_cancelled(self, event: Event) -> None:
        mission = self._missions.get(event.aggregate_id)
        if mission is None:
            return
        mission["status"] = "cancelled"
        mission["completed_at"] = event.timestamp.isoformat()
        mission["version"] = event.version


# ---------------------------------------------------------------------------
# EconomyProjection
# ---------------------------------------------------------------------------

class EconomyProjection(Projection):
    """
    Maintains a per-agent credit ledger derived from economy events.

    Handles:

    * ``economy.credit_earned``     — add credits to agent balance
    * ``economy.credit_spent``      — deduct credits from agent balance
    * ``economy.credit_transferred`` — move credits between agents
    * ``economy.balance_adjusted``  — arbitrary balance delta (admin)
    """

    def __init__(self, event_store: EventStore) -> None:
        super().__init__(event_store)
        # agent_id → current balance
        self._balances: Dict[str, float] = defaultdict(float)
        # agent_id → list of (timestamp, delta, reason, running_balance)
        self._ledger: Dict[str, List[Tuple[str, float, str, float]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Projection interface
    # ------------------------------------------------------------------

    async def rebuild(self) -> None:
        """Replay all economy events to rebuild the ledger."""
        logger.info("EconomyProjection.rebuild() started")
        self._balances.clear()
        self._ledger.clear()

        events = await self.event_store.get_all_events()
        economy_event_types = {
            "economy.credit_earned",
            "economy.credit_spent",
            "economy.credit_transferred",
            "economy.balance_adjusted",
        }
        relevant = [e for e in events if e.event_type in economy_event_types]
        for event in sorted(relevant, key=lambda e: (e.timestamp, e.version)):
            await self.handle_event(event)

        logger.info(
            "EconomyProjection.rebuild() complete — %d agent ledger(s) loaded",
            len(self._balances),
        )

    async def handle_event(self, event: Event) -> None:
        """Apply a single economy event to the ledger."""
        handler_name = "_on_" + event.event_type.replace(".", "_")
        handler = getattr(self, handler_name, None)
        if handler is not None:
            handler(event)
        else:
            logger.debug(
                "EconomyProjection: no handler for event type '%s'", event.event_type
            )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_balance(self, agent_id: str) -> float:
        """Return the current credit balance for *agent_id*."""
        return self._balances.get(agent_id, 0.0)

    def get_ledger(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Tuple[str, float, str, float]]:
        """
        Return the transaction ledger for *agent_id*.

        Each entry is a ``(timestamp_iso, delta, reason, running_balance)`` tuple,
        ordered from oldest to newest.
        """
        entries = self._ledger.get(agent_id, [])
        return entries[offset : offset + limit]

    def get_all_balances(self) -> Dict[str, float]:
        """Return a snapshot of all agent balances."""
        return dict(self._balances)

    # ------------------------------------------------------------------
    # Event handlers (private)
    # ------------------------------------------------------------------

    def _apply_delta(self, agent_id: str, delta: float, reason: str, ts: datetime) -> None:
        """Apply *delta* to *agent_id*'s balance and record the ledger entry."""
        self._balances[agent_id] = self._balances.get(agent_id, 0.0) + delta
        self._ledger[agent_id].append(
            (ts.isoformat(), delta, reason, self._balances[agent_id])
        )

    def _on_economy_credit_earned(self, event: Event) -> None:
        amount = float(event.data.get("amount", 0.0))
        reason = event.data.get("reason", "credit_earned")
        self._apply_delta(event.aggregate_id, amount, reason, event.timestamp)

    def _on_economy_credit_spent(self, event: Event) -> None:
        amount = float(event.data.get("amount", 0.0))
        reason = event.data.get("reason", "credit_spent")
        self._apply_delta(event.aggregate_id, -amount, reason, event.timestamp)

    def _on_economy_credit_transferred(self, event: Event) -> None:
        amount = float(event.data.get("amount", 0.0))
        to_agent = event.data.get("to_agent_id")
        # Debit the sender
        self._apply_delta(
            event.aggregate_id,
            -amount,
            f"transfer_to:{to_agent}",
            event.timestamp,
        )
        # Credit the receiver (if known)
        if to_agent:
            self._apply_delta(
                to_agent,
                amount,
                f"transfer_from:{event.aggregate_id}",
                event.timestamp,
            )

    def _on_economy_balance_adjusted(self, event: Event) -> None:
        amount = float(event.data.get("amount", 0.0))
        reason = event.data.get("reason", "balance_adjusted")
        self._apply_delta(event.aggregate_id, amount, reason, event.timestamp)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def create_projections(event_store: EventStore) -> Dict[str, Projection]:
    """
    Instantiate all concrete projections backed by *event_store*.

    Returns a dict keyed by projection name for easy access::

        projections = create_projections(event_store)
        agent_proj: AgentProjection = projections["agent"]
        mission_proj: MissionProjection = projections["mission"]
        economy_proj: EconomyProjection = projections["economy"]

    Call ``await projection.rebuild()`` on each before serving queries.
    """
    return {
        "agent": AgentProjection(event_store),
        "mission": MissionProjection(event_store),
        "economy": EconomyProjection(event_store),
    }


__all__ = [
    "AgentProjection",
    "MissionProjection",
    "EconomyProjection",
    "create_projections",
]
