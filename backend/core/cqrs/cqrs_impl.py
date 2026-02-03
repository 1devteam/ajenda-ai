"""
CQRS (Command Query Responsibility Segregation) Implementation for Omnipath v5.0
Separates read and write operations for scalability and performance

Built with Pride for Obex Blackvault
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, TypeVar, Type, Optional, List
from dataclasses import dataclass
from enum import Enum

from backend.core.logging_config import get_logger, LoggerMixin
from backend.core.event_sourcing.event_store_impl import EventStore, Event


logger = get_logger(__name__)

# Type variables
TCommand = TypeVar('TCommand', bound='Command')
TQuery = TypeVar('TQuery', bound='Query')
TResult = TypeVar('TResult')


# ============================================================================
# Commands (Write Side)
# ============================================================================

@dataclass
class Command(ABC):
    """
    Base class for all commands
    Commands represent intentions to change state
    """
    pass


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
        pass
    
    async def emit_event(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
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
            metadata=metadata
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
            aggregate_type='agent',
            event_type='agent.created',
            data={
                'tenant_id': command.tenant_id,
                'name': command.name,
                'model': command.model,
                'capabilities': command.capabilities,
                'system_prompt': command.system_prompt,
                'temperature': command.temperature
            }
        )
        
        self.log_info(
            f"Agent created: {command.name}",
            agent_id=agent_id,
            tenant_id=command.tenant_id
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
            aggregate_type='mission',
            event_type='mission.started',
            data={
                'agent_id': command.agent_id,
                'command': command.command,
                'context': command.context
            }
        )
        
        self.log_info(
            f"Mission started",
            mission_id=command.mission_id,
            agent_id=command.agent_id
        )


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
            aggregate_type='mission',
            event_type='mission.completed',
            data={
                'result': command.result,
                'tokens_used': command.tokens_used,
                'cost': command.cost
            }
        )
        
        self.log_info(
            f"Mission completed",
            mission_id=command.mission_id,
            tokens_used=command.tokens_used,
            cost=command.cost
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
            aggregate_type='agent',
            event_type='economy.balance_adjusted',
            data={
                'amount': command.amount,
                'reason': command.reason
            }
        )
        
        self.log_info(
            f"Credit adjusted",
            agent_id=command.agent_id,
            amount=command.amount,
            reason=command.reason
        )
        
        # Return new balance (would be calculated from events)
        return command.amount


# ============================================================================
# Queries (Read Side)
# ============================================================================

@dataclass
class Query(ABC):
    """
    Base class for all queries
    Queries represent requests for data
    """
    pass


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
        pass


class GetAgentQueryHandler(QueryHandler[GetAgentQuery, Optional[Dict[str, Any]]]):
    """Handler for GetAgentQuery"""
    
    def __init__(self, read_model: 'AgentReadModel'):
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
            self.log_debug(f"Agent retrieved", agent_id=query.agent_id)
        else:
            self.log_warning(f"Agent not found", agent_id=query.agent_id)
        
        return agent


class ListAgentsQueryHandler(QueryHandler[ListAgentsQuery, List[Dict[str, Any]]]):
    """Handler for ListAgentsQuery"""
    
    def __init__(self, read_model: 'AgentReadModel'):
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
            tenant_id=query.tenant_id,
            limit=query.limit,
            offset=query.offset
        )
        
        self.log_debug(
            f"Agents listed: {len(agents)}",
            tenant_id=query.tenant_id
        )
        
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
        pass


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
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List agents by tenant"""
        # In production, this would query a denormalized table
        # For now, return cached agents
        agents = [
            agent for agent in self._cache.values()
            if agent.get('tenant_id') == tenant_id
        ]
        
        return agents[offset:offset + limit]
    
    async def rebuild(self) -> None:
        """Rebuild read model from all agent events"""
        self.log_info("Rebuilding agent read model")
        
        # Get all agent events
        events = await self.event_store.get_all_events()
        
        # Group by aggregate_id
        agents_events: Dict[str, List[Event]] = {}
        for event in events:
            if event.aggregate_type == 'agent':
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
            if event.event_type == 'agent.created':
                agent = {
                    'id': event.aggregate_id,
                    **event.data,
                    'created_at': event.timestamp.isoformat(),
                    'version': event.version
                }
            elif event.event_type == 'agent.updated':
                agent.update(event.data)
                agent['version'] = event.version
            elif event.event_type == 'economy.balance_adjusted':
                current_balance = agent.get('balance', 0)
                agent['balance'] = current_balance + event.data['amount']
        
        return agent


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
        self,
        command_type: Type[TCommand],
        handler: CommandHandler[TCommand, Any]
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
    
    def register(
        self,
        query_type: Type[TQuery],
        handler: QueryHandler[TQuery, Any]
    ) -> None:
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
