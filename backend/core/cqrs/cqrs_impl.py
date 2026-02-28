"""
CQRS (Command Query Responsibility Segregation) Implementation for Omnipath v5.0
Separates read and write operations for scalability and performance

Built with Pride for Obex Blackvault
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, TypeVar, Type, Optional, List
from dataclasses import dataclass

from backend.core.logging_config import get_logger, LoggerMixin
from backend.core.event_sourcing.event_store_impl import EventStore, Event


logger = get_logger(__name__)

# Type variables
TCommand = TypeVar("TCommand", bound="Command")
TQuery = TypeVar("TQuery", bound="Query")
TResult = TypeVar("TResult")


# ============================================================================
# Commands (Write Side)
# ============================================================================


@dataclass
class Command(ABC):
    """
    Base class for all commands
    Commands represent intentions to change state
    """


@dataclass
class CreateAgentCommand(Command):
    """Command to create a new agent"""

    tenant_id: str
    name: str
    model: str
    capabilities: List[str]
    system_prompt: str
    temperature: float = 0.7


@dataclass
class StartMissionCommand(Command):
    """Command to start a mission"""

    mission_id: str
    agent_id: str
    command: str
    context: Dict[str, Any]


@dataclass
class CompleteMissionCommand(Command):
    """Command to complete a mission"""

    mission_id: str
    result: Dict[str, Any]
    tokens_used: int
    cost: float


@dataclass
class AdjustCreditCommand(Command):
    """Command to adjust agent credit balance"""

    agent_id: str
    amount: float
    reason: str


# ============================================================================
# Command Handlers
# ============================================================================


class CommandHandler(ABC, LoggerMixin, Generic[TCommand, TResult]):
    """
    Base class for command handlers
    Handles write operations and emits events
    """

    def __init__(self, event_store: EventStore):
        """
        Initialize command handler

        Args:
            event_store: Event store for persisting events
        """
        self.event_store = event_store

    @abstractmethod
    async def handle(self, command: TCommand) -> TResult:
        """
        Handle command and return result

        Args:
            command: Command to handle

        Returns:
            Result of command execution
        """

    async def emit_event(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """
        Emit domain event

        Args:
            aggregate_id: ID of the aggregate
            aggregate_type: Type of the aggregate
            event_type: Type of event
            data: Event data
            metadata: Optional metadata

        Returns:
            Created event
        """
        return await self.event_store.append(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            data=data,
            metadata=metadata,
        )


class CreateAgentCommandHandler(CommandHandler[CreateAgentCommand, str]):
    """Handler for CreateAgentCommand"""

    async def handle(self, command: CreateAgentCommand) -> str:
        """
        Create new agent

        Args:
            command: Create agent command

        Returns:
            Agent ID
        """
        import uuid

        agent_id = str(uuid.uuid4())

        # Emit agent created event
        await self.emit_event(
            aggregate_id=agent_id,
            aggregate_type="agent",
            event_type="agent.created",
            data={
                "tenant_id": command.tenant_id,
                "name": command.name,
                "model": command.model,
                "capabilities": command.capabilities,
                "system_prompt": command.system_prompt,
                "temperature": command.temperature,
            },
        )

        self.log_info(
            f"Agent created: {command.name}",
            agent_id=agent_id,
            tenant_id=command.tenant_id,
        )

        return agent_id


class StartMissionCommandHandler(CommandHandler[StartMissionCommand, None]):
    """Handler for StartMissionCommand"""

    async def handle(self, command: StartMissionCommand) -> None:
        """
        Start mission

        Args:
            command: Start mission command
        """
        # Emit mission started event
        await self.emit_event(
            aggregate_id=command.mission_id,
            aggregate_type="mission",
            event_type="mission.started",
            data={
                "agent_id": command.agent_id,
                "command": command.command,
                "context": command.context,
            },
        )

        self.log_info("Mission started", mission_id=command.mission_id, agent_id=command.agent_id)


class CompleteMissionCommandHandler(CommandHandler[CompleteMissionCommand, None]):
    """Handler for CompleteMissionCommand"""

    async def handle(self, command: CompleteMissionCommand) -> None:
        """
        Complete mission

        Args:
            command: Complete mission command
        """
        # Emit mission completed event
        await self.emit_event(
            aggregate_id=command.mission_id,
            aggregate_type="mission",
            event_type="mission.completed",
            data={
                "result": command.result,
                "tokens_used": command.tokens_used,
                "cost": command.cost,
            },
        )

        self.log_info(
            "Mission completed",
            mission_id=command.mission_id,
            tokens_used=command.tokens_used,
            cost=command.cost,
        )


class AdjustCreditCommandHandler(CommandHandler[AdjustCreditCommand, float]):
    """Handler for AdjustCreditCommand"""

    async def handle(self, command: AdjustCreditCommand) -> float:
        """
        Adjust agent credit balance

        Args:
            command: Adjust credit command

        Returns:
            New balance
        """
        # Emit balance adjusted event
        await self.emit_event(
            aggregate_id=command.agent_id,
            aggregate_type="agent",
            event_type="economy.balance_adjusted",
            data={"amount": command.amount, "reason": command.reason},
        )

        self.log_info(
            "Credit adjusted",
            agent_id=command.agent_id,
            amount=command.amount,
            reason=command.reason,
        )

        # Return new balance (would be calculated from events)
        return command.amount


@dataclass
class UpdateAgentCommand(Command):
    """Command to update an existing agent's configuration."""

    agent_id: str
    name: Optional[str] = None
    model: Optional[str] = None
    capabilities: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None


class UpdateAgentCommandHandler(CommandHandler[UpdateAgentCommand, None]):
    """Handler for UpdateAgentCommand."""

    async def handle(self, command: UpdateAgentCommand) -> None:
        """
        Update an existing agent and emit an ``agent.updated`` event.

        Only fields that are explicitly provided (non-``None``) are included
        in the event payload so downstream projections can apply partial
        updates without overwriting unchanged fields.

        Args:
            command: Update agent command.
        """
        changes: Dict[str, Any] = {}
        if command.name is not None:
            changes["name"] = command.name
        if command.model is not None:
            changes["model"] = command.model
        if command.capabilities is not None:
            changes["capabilities"] = command.capabilities
        if command.system_prompt is not None:
            changes["system_prompt"] = command.system_prompt
        if command.temperature is not None:
            changes["temperature"] = command.temperature

        if not changes:
            self.log_info(
                "UpdateAgentCommand received with no changes — skipping event emit.",
                agent_id=command.agent_id,
            )
            return

        await self.emit_event(
            aggregate_id=command.agent_id,
            aggregate_type="agent",
            event_type="agent.updated",
            data=changes,
        )

        self.log_info(
            "Agent updated",
            agent_id=command.agent_id,
            changed_fields=list(changes.keys()),
        )


# ============================================================================
# Queries (Read Side)
# ============================================================================


@dataclass
class Query(ABC):
    """
    Base class for all queries
    Queries represent requests for data
    """


@dataclass
class GetAgentQuery(Query):
    """Query to get agent by ID"""

    agent_id: str


@dataclass
class ListAgentsQuery(Query):
    """Query to list agents"""

    tenant_id: str
    limit: int = 100
    offset: int = 0


@dataclass
class GetMissionQuery(Query):
    """Query to get mission by ID"""

    mission_id: str


@dataclass
class ListMissionsQuery(Query):
    """Query to list missions"""

    agent_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = 100
    offset: int = 0


@dataclass
class GetAgentBalanceQuery(Query):
    """Query to get agent balance"""

    agent_id: str


@dataclass
class GetPerformanceMetricsQuery(Query):
    """Query to get performance metrics"""

    agent_id: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None


# ============================================================================
# Query Handlers
# ============================================================================


class QueryHandler(ABC, LoggerMixin, Generic[TQuery, TResult]):
    """
    Base class for query handlers
    Handles read operations from read models
    """

    @abstractmethod
    async def handle(self, query: TQuery) -> TResult:
        """
        Handle query and return result

        Args:
            query: Query to handle

        Returns:
            Query result
        """


class GetAgentQueryHandler(QueryHandler[GetAgentQuery, Optional[Dict[str, Any]]]):
    """Handler for GetAgentQuery"""

    def __init__(self, read_model: "AgentReadModel"):
        """
        Initialize handler

        Args:
            read_model: Agent read model
        """
        self.read_model = read_model

    async def handle(self, query: GetAgentQuery) -> Optional[Dict[str, Any]]:
        """
        Get agent by ID

        Args:
            query: Get agent query

        Returns:
            Agent data or None
        """
        agent = await self.read_model.get_by_id(query.agent_id)

        if agent:
            self.log_debug("Agent retrieved", agent_id=query.agent_id)
        else:
            self.log_warning("Agent not found", agent_id=query.agent_id)

        return agent


class ListAgentsQueryHandler(QueryHandler[ListAgentsQuery, List[Dict[str, Any]]]):
    """Handler for ListAgentsQuery"""

    def __init__(self, read_model: "AgentReadModel"):
        """
        Initialize handler

        Args:
            read_model: Agent read model
        """
        self.read_model = read_model

    async def handle(self, query: ListAgentsQuery) -> List[Dict[str, Any]]:
        """
        List agents

        Args:
            query: List agents query

        Returns:
            List of agents
        """
        agents = await self.read_model.list_by_tenant(
            tenant_id=query.tenant_id, limit=query.limit, offset=query.offset
        )

        self.log_debug(f"Agents listed: {len(agents)}", tenant_id=query.tenant_id)

        return agents


# ============================================================================
# Read Models
# ============================================================================


class ReadModel(ABC, LoggerMixin):
    """
    Base class for read models
    Read models are optimized for queries
    """

    @abstractmethod
    async def rebuild(self) -> None:
        """Rebuild read model from events"""


class AgentReadModel(ReadModel):
    """
    Read model for agent queries
    Denormalized view optimized for reads
    """

    def __init__(self, event_store: EventStore):
        """
        Initialize read model

        Args:
            event_store: Event store to read from
        """
        self.event_store = event_store
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def get_by_id(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent by ID"""
        # Check cache first
        if agent_id in self._cache:
            return self._cache[agent_id]

        # Rebuild from events
        events = await self.event_store.get_events(agent_id)

        if not events:
            return None

        agent = self._build_from_events(events)
        self._cache[agent_id] = agent

        return agent

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List agents by tenant"""
        # In production, this would query a denormalized table
        # For now, return cached agents
        agents = [agent for agent in self._cache.values() if agent.get("tenant_id") == tenant_id]

        return agents[offset : offset + limit]

    async def rebuild(self) -> None:
        """Rebuild read model from all agent events"""
        self.log_info("Rebuilding agent read model")

        # Get all agent events
        events = await self.event_store.get_all_events()

        # Group by aggregate_id
        agents_events: Dict[str, List[Event]] = {}
        for event in events:
            if event.aggregate_type == "agent":
                if event.aggregate_id not in agents_events:
                    agents_events[event.aggregate_id] = []
                agents_events[event.aggregate_id].append(event)

        # Rebuild each agent
        for agent_id, agent_events in agents_events.items():
            agent = self._build_from_events(agent_events)
            self._cache[agent_id] = agent

        self.log_info(f"Agent read model rebuilt: {len(self._cache)} agents")

    def _build_from_events(self, events: List[Event]) -> Dict[str, Any]:
        """Build agent state from events"""
        agent = {}

        for event in sorted(events, key=lambda e: e.version):
            if event.event_type == "agent.created":
                agent = {
                    "id": event.aggregate_id,
                    **event.data,
                    "created_at": event.timestamp.isoformat(),
                    "version": event.version,
                }
            elif event.event_type == "agent.updated":
                agent.update(event.data)
                agent["version"] = event.version
            elif event.event_type == "economy.balance_adjusted":
                current_balance = agent.get("balance", 0)
                agent["balance"] = current_balance + event.data["amount"]

        return agent


class MissionReadModel(ReadModel):
    """
    Read model for mission queries.

    Maintains a denormalised, in-memory view of all missions keyed by
    ``mission_id``.  Rebuilt from the event store on demand.
    """

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store
        self._cache: Dict[str, Dict[str, Any]] = {}
        # agent_id → list of mission_ids for fast per-agent listing
        self._by_agent: Dict[str, List[str]] = {}

    async def get_by_id(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Return mission state for *mission_id*, or ``None`` if not found."""
        if mission_id in self._cache:
            return self._cache[mission_id]
        events = await self.event_store.get_events(mission_id)
        if not events:
            return None
        mission = self._build_from_events(events)
        self._cache[mission_id] = mission
        agent_id = mission.get("agent_id")
        if agent_id:
            self._by_agent.setdefault(agent_id, [])
            if mission_id not in self._by_agent[agent_id]:
                self._by_agent[agent_id].append(mission_id)
        return mission

    async def list_missions(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return missions, optionally filtered by *agent_id* and/or *status*."""
        if agent_id is not None:
            mission_ids = self._by_agent.get(agent_id, [])
            missions = [self._cache[mid] for mid in mission_ids if mid in self._cache]
        else:
            missions = list(self._cache.values())

        if status is not None:
            missions = [m for m in missions if m.get("status") == status]

        return missions[offset : offset + limit]

    async def rebuild(self) -> None:
        """Rebuild the read model from all mission events in the event store."""
        self.log_info("Rebuilding mission read model")
        self._cache.clear()
        self._by_agent.clear()

        events = await self.event_store.get_all_events()
        mission_events: Dict[str, List[Event]] = {}
        for event in events:
            if event.aggregate_type == "mission":
                mission_events.setdefault(event.aggregate_id, []).append(event)

        for mission_id, evts in mission_events.items():
            mission = self._build_from_events(evts)
            self._cache[mission_id] = mission
            agent_id = mission.get("agent_id")
            if agent_id:
                self._by_agent.setdefault(agent_id, [])
                if mission_id not in self._by_agent[agent_id]:
                    self._by_agent[agent_id].append(mission_id)

        self.log_info("Mission read model rebuilt: %d missions", len(self._cache))

    def _build_from_events(self, events: List[Event]) -> Dict[str, Any]:
        """Derive mission state by replaying *events* in version order."""
        mission: Dict[str, Any] = {}
        for event in sorted(events, key=lambda e: e.version):
            if event.event_type == "mission.created":
                mission = {
                    "id": event.aggregate_id,
                    "status": "created",
                    "created_at": event.timestamp.isoformat(),
                    "version": event.version,
                    **event.data,
                }
            elif event.event_type == "mission.started":
                mission["status"] = "running"
                mission["started_at"] = event.timestamp.isoformat()
                mission["version"] = event.version
            elif event.event_type == "mission.completed":
                mission["status"] = "completed"
                mission["result"] = event.data.get("result")
                mission["tokens_used"] = event.data.get("tokens_used", 0)
                mission["cost"] = event.data.get("cost", 0.0)
                mission["completed_at"] = event.timestamp.isoformat()
                mission["version"] = event.version
            elif event.event_type == "mission.failed":
                mission["status"] = "failed"
                mission["error"] = event.data.get("error")
                mission["completed_at"] = event.timestamp.isoformat()
                mission["version"] = event.version
            elif event.event_type == "mission.cancelled":
                mission["status"] = "cancelled"
                mission["completed_at"] = event.timestamp.isoformat()
                mission["version"] = event.version
        return mission


class GetMissionQueryHandler(QueryHandler[GetMissionQuery, Optional[Dict[str, Any]]]):
    """Handler for GetMissionQuery — returns a single mission by ID."""

    def __init__(self, read_model: MissionReadModel) -> None:
        self.read_model = read_model

    async def handle(self, query: GetMissionQuery) -> Optional[Dict[str, Any]]:
        mission = await self.read_model.get_by_id(query.mission_id)
        if mission:
            self.log_debug("Mission retrieved", mission_id=query.mission_id)
        else:
            self.log_warning("Mission not found", mission_id=query.mission_id)
        return mission


class ListMissionsQueryHandler(QueryHandler[ListMissionsQuery, List[Dict[str, Any]]]):
    """Handler for ListMissionsQuery — returns a filtered list of missions."""

    def __init__(self, read_model: MissionReadModel) -> None:
        self.read_model = read_model

    async def handle(self, query: ListMissionsQuery) -> List[Dict[str, Any]]:
        missions = await self.read_model.list_missions(
            agent_id=query.agent_id,
            status=query.status,
            limit=query.limit,
            offset=query.offset,
        )
        self.log_debug(
            "Missions listed: %d",
            len(missions),
            agent_id=query.agent_id,
            status=query.status,
        )
        return missions


class GetAgentBalanceQueryHandler(QueryHandler[GetAgentBalanceQuery, float]):
    """
    Handler for GetAgentBalanceQuery.

    Derives the current balance by summing all ``economy.balance_adjusted``,
    ``economy.credit_earned``, and ``economy.credit_spent`` events for the
    agent from the event store.
    """

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store

    async def handle(self, query: GetAgentBalanceQuery) -> float:
        events = await self.event_store.get_events(query.agent_id)
        balance = 1000.0  # default starting balance
        for event in sorted(events, key=lambda e: e.version):
            if event.event_type == "economy.balance_adjusted":
                balance += float(event.data.get("amount", 0.0))
            elif event.event_type == "economy.credit_earned":
                balance += float(event.data.get("amount", 0.0))
            elif event.event_type == "economy.credit_spent":
                balance -= float(event.data.get("amount", 0.0))
        self.log_debug("Balance calculated", agent_id=query.agent_id, balance=balance)
        return balance


class GetPerformanceMetricsQueryHandler(QueryHandler[GetPerformanceMetricsQuery, Dict[str, Any]]):
    """
    Handler for GetPerformanceMetricsQuery.

    Aggregates mission outcome events to produce per-agent (or portfolio-wide)
    performance metrics: total missions, success rate, average cost, and
    average token usage.
    """

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store

    async def handle(self, query: GetPerformanceMetricsQuery) -> Dict[str, Any]:
        from datetime import datetime as _dt

        # Fetch relevant events
        all_events = await self.event_store.get_all_events()

        # Apply optional time filters
        from_dt = _dt.fromisoformat(query.from_date) if query.from_date else None
        to_dt = _dt.fromisoformat(query.to_date) if query.to_date else None

        total = 0
        completed = 0
        failed = 0
        total_cost = 0.0
        total_tokens = 0

        for event in all_events:
            if event.aggregate_type != "mission":
                continue
            if from_dt and event.timestamp < from_dt:
                continue
            if to_dt and event.timestamp > to_dt:
                continue

            # If filtering by agent, we need the agent_id from the event data
            if query.agent_id:
                if event.data.get("agent_id") != query.agent_id:
                    continue

            if event.event_type == "mission.started":
                total += 1
            elif event.event_type == "mission.completed":
                completed += 1
                total_cost += float(event.data.get("cost", 0.0))
                total_tokens += int(event.data.get("tokens_used", 0))
            elif event.event_type == "mission.failed":
                failed += 1

        success_rate = (completed / total * 100) if total > 0 else 0.0
        avg_cost = (total_cost / completed) if completed > 0 else 0.0
        avg_tokens = (total_tokens / completed) if completed > 0 else 0

        metrics = {
            "agent_id": query.agent_id,
            "from_date": query.from_date,
            "to_date": query.to_date,
            "total_missions": total,
            "completed_missions": completed,
            "failed_missions": failed,
            "success_rate_pct": round(success_rate, 2),
            "average_cost": round(avg_cost, 4),
            "average_tokens_used": avg_tokens,
            "total_cost": round(total_cost, 4),
            "total_tokens_used": total_tokens,
        }

        self.log_debug(
            "Performance metrics calculated",
            agent_id=query.agent_id,
            total=total,
            success_rate=success_rate,
        )
        return metrics


# ============================================================================
# Command/Query Bus
# ============================================================================


class CommandBus(LoggerMixin):
    """
    Command bus for dispatching commands to handlers
    """

    def __init__(self):
        """Initialize command bus"""
        self._handlers: Dict[Type[Command], CommandHandler] = {}

    def register(
        self, command_type: Type[TCommand], handler: CommandHandler[TCommand, Any]
    ) -> None:
        """
        Register command handler

        Args:
            command_type: Type of command
            handler: Handler for the command
        """
        self._handlers[command_type] = handler
        self.log_info(f"Command handler registered: {command_type.__name__}")

    async def dispatch(self, command: Command) -> Any:
        """
        Dispatch command to handler

        Args:
            command: Command to dispatch

        Returns:
            Result from handler

        Raises:
            ValueError: If no handler registered
        """
        handler = self._handlers.get(type(command))

        if not handler:
            raise ValueError(f"No handler registered for {type(command).__name__}")

        self.log_info(f"Dispatching command: {type(command).__name__}")

        return await handler.handle(command)


class QueryBus(LoggerMixin):
    """
    Query bus for dispatching queries to handlers
    """

    def __init__(self):
        """Initialize query bus"""
        self._handlers: Dict[Type[Query], QueryHandler] = {}

    def register(self, query_type: Type[TQuery], handler: QueryHandler[TQuery, Any]) -> None:
        """
        Register query handler

        Args:
            query_type: Type of query
            handler: Handler for the query
        """
        self._handlers[query_type] = handler
        self.log_info(f"Query handler registered: {query_type.__name__}")

    async def dispatch(self, query: Query) -> Any:
        """
        Dispatch query to handler

        Args:
            query: Query to dispatch

        Returns:
            Result from handler

        Raises:
            ValueError: If no handler registered
        """
        handler = self._handlers.get(type(query))

        if not handler:
            raise ValueError(f"No handler registered for {type(query).__name__}")

        self.log_debug(f"Dispatching query: {type(query).__name__}")

        return await handler.handle(query)
