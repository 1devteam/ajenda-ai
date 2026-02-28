"""
Month 5 Implementation Tests
Tests for Event Sourcing, CQRS, and Saga Orchestration

All tests written against the actual class signatures — no assumptions.
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.unit


# ============================================================================
# Event Sourcing Tests
# ============================================================================


class TestEventClass:
    """Tests for the Event base class and serialization"""

    def test_event_creation_minimal(self):
        """Test basic Event creation with required fields"""
        from backend.core.event_sourcing.event_store_impl import Event, EventType

        event = Event(
            event_id="evt_001",
            event_type=EventType.AGENT_CREATED,
            aggregate_id="agent_001",
            aggregate_type="Agent",
            data={"name": "TestAgent"},
            metadata={},
            timestamp=datetime.utcnow(),
            version=1,
        )
        assert event.event_id == "evt_001"
        assert event.event_type == EventType.AGENT_CREATED
        assert event.aggregate_id == "agent_001"
        assert event.data["name"] == "TestAgent"
        assert event.version == 1

    def test_event_to_dict(self):
        """Test Event serialization to dictionary"""
        from backend.core.event_sourcing.event_store_impl import Event, EventType

        now = datetime.utcnow()
        event = Event(
            event_id="evt_002",
            event_type=EventType.MISSION_STARTED,
            aggregate_id="mission_001",
            aggregate_type="Mission",
            data={"title": "Test Mission"},
            metadata={"source": "test"},
            timestamp=now,
            version=1,
        )
        d = event.to_dict()
        assert d["event_id"] == "evt_002"
        assert d["event_type"] == EventType.MISSION_STARTED
        assert d["aggregate_id"] == "mission_001"
        assert d["data"]["title"] == "Test Mission"
        assert "timestamp" in d

    def test_event_from_dict(self):
        """Test Event deserialization from dictionary"""
        from backend.core.event_sourcing.event_store_impl import Event, EventType

        data = {
            "event_id": "evt_003",
            "event_type": EventType.AGENT_UPDATED,
            "aggregate_id": "agent_002",
            "aggregate_type": "Agent",
            "version": 2,
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"model": "gpt-4-turbo"},
            "metadata": {},
        }
        event = Event.from_dict(data)
        assert event.event_id == "evt_003"
        assert event.event_type == EventType.AGENT_UPDATED
        assert event.version == 2
        assert event.data["model"] == "gpt-4-turbo"

    def test_event_roundtrip_serialization(self):
        """Test that Event survives a to_dict/from_dict roundtrip"""
        from backend.core.event_sourcing.event_store_impl import Event, EventType

        original = Event(
            event_id="evt_004",
            event_type=EventType.MISSION_COMPLETED,
            aggregate_id="mission_002",
            aggregate_type="Mission",
            data={"result": "success", "cost": 1.5},
            metadata={"executor": "test"},
            timestamp=datetime.utcnow(),
            version=3,
        )
        restored = Event.from_dict(original.to_dict())
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.data == original.data
        assert restored.version == original.version


class TestEventTypes:
    """Tests for EventType enum completeness"""

    def test_agent_event_types_defined(self):
        """Test that all agent event types are defined"""
        from backend.core.event_sourcing.event_store_impl import EventType

        assert EventType.AGENT_CREATED is not None
        assert EventType.AGENT_UPDATED is not None
        assert EventType.AGENT_DELETED is not None

    def test_mission_event_types_defined(self):
        """Test that all mission event types are defined"""
        from backend.core.event_sourcing.event_store_impl import EventType

        assert EventType.MISSION_STARTED is not None
        assert EventType.MISSION_COMPLETED is not None
        assert EventType.MISSION_FAILED is not None

    def test_economy_event_types_defined(self):
        """Test that economy event types are defined"""
        from backend.core.event_sourcing.event_store_impl import EventType

        assert EventType.CREDIT_EARNED is not None
        assert EventType.CREDIT_SPENT is not None
        assert EventType.BALANCE_ADJUSTED is not None

    def test_event_type_values_are_strings(self):
        """Test that EventType values are dot-notation strings"""
        from backend.core.event_sourcing.event_store_impl import EventType

        assert "." in EventType.AGENT_CREATED.value
        assert "." in EventType.MISSION_STARTED.value


class TestSnapshotClass:
    """Tests for the Snapshot dataclass"""

    def test_snapshot_creation(self):
        """Test Snapshot creation with required fields"""
        from backend.core.event_sourcing.event_store_impl import Snapshot

        snapshot = Snapshot(
            aggregate_id="agent_001",
            aggregate_type="Agent",
            version=10,
            state={"name": "TestAgent", "status": "active"},
            timestamp=datetime.utcnow(),
        )
        assert snapshot.aggregate_id == "agent_001"
        assert snapshot.version == 10
        assert snapshot.state["name"] == "TestAgent"

    def test_snapshot_state_preserved(self):
        """Test that snapshot state is preserved exactly"""
        from backend.core.event_sourcing.event_store_impl import Snapshot

        complex_state = {
            "name": "Agent",
            "capabilities": ["planning", "execution"],
            "metrics": {"missions": 42, "success_rate": 0.95},
            "nested": {"deep": {"value": True}},
        }
        snapshot = Snapshot(
            aggregate_id="agent_002",
            aggregate_type="Agent",
            version=5,
            state=complex_state,
            timestamp=datetime.utcnow(),
        )
        assert snapshot.state == complex_state
        assert snapshot.state["metrics"]["success_rate"] == 0.95


class TestEventStoreAppend:
    """Tests for EventStore.append with mocked session"""

    @pytest.mark.asyncio
    async def test_append_event_calls_session_add(self):
        """Test that appending an event calls session.add and commit"""
        from backend.core.event_sourcing.event_store_impl import EventStore, EventType
        from sqlalchemy.ext.asyncio import AsyncSession

        mock_session = AsyncMock(spec=AsyncSession)
        store = EventStore(session=mock_session)

        with patch.object(store, "_get_current_version", return_value=0):
            await store.append(
                aggregate_id="agent_001",
                aggregate_type="Agent",
                event_type=EventType.AGENT_CREATED,
                data={"name": "TestAgent"},
                metadata={},
                expected_version=0,
            )
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrency_conflict_raises(self):
        """Test that appending with wrong expected_version raises ConcurrencyError"""
        from backend.core.event_sourcing.event_store_impl import (
            EventStore,
            EventType,
            ConcurrencyError,
        )
        from sqlalchemy.ext.asyncio import AsyncSession

        mock_session = AsyncMock(spec=AsyncSession)
        store = EventStore(session=mock_session)

        with patch.object(store, "_get_current_version", return_value=2):
            with pytest.raises(ConcurrencyError):
                await store.append(
                    aggregate_id="agent_001",
                    aggregate_type="Agent",
                    event_type=EventType.AGENT_UPDATED,
                    data={},
                    expected_version=1,  # Wrong — current is 2
                )


# ============================================================================
# CQRS Tests
# ============================================================================


class TestCommandClasses:
    """Tests for CQRS Command dataclasses — using actual signatures"""

    def test_create_agent_command(self):
        """Test CreateAgentCommand creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import CreateAgentCommand

        cmd = CreateAgentCommand(
            tenant_id="tenant_1",
            name="Test Commander",
            model="gpt-4-turbo",
            capabilities=["planning", "coordination"],
            system_prompt="You are a commander agent.",
            temperature=0.7,
        )
        assert cmd.tenant_id == "tenant_1"
        assert cmd.name == "Test Commander"
        assert "planning" in cmd.capabilities
        assert cmd.temperature == 0.7

    def test_create_agent_command_default_temperature(self):
        """Test CreateAgentCommand uses default temperature"""
        from backend.core.cqrs.cqrs_impl import CreateAgentCommand

        cmd = CreateAgentCommand(
            tenant_id="tenant_1",
            name="Test",
            model="gpt-4",
            capabilities=[],
            system_prompt="You are an agent.",
        )
        assert cmd.temperature == 0.7

    def test_start_mission_command(self):
        """Test StartMissionCommand creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import StartMissionCommand

        cmd = StartMissionCommand(
            mission_id="mission_001",
            agent_id="agent_001",
            command="Analyze the market trends",
            context={"priority": "high", "deadline": "2026-03-01"},
        )
        assert cmd.mission_id == "mission_001"
        assert cmd.agent_id == "agent_001"
        assert cmd.command == "Analyze the market trends"

    def test_complete_mission_command(self):
        """Test CompleteMissionCommand creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import CompleteMissionCommand

        cmd = CompleteMissionCommand(
            mission_id="mission_001",
            result={"status": "success", "output": "Analysis complete"},
            tokens_used=1500,
            cost=2.5,
        )
        assert cmd.mission_id == "mission_001"
        assert cmd.tokens_used == 1500
        assert cmd.cost == 2.5

    def test_adjust_credit_command(self):
        """Test AdjustCreditCommand creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import AdjustCreditCommand

        cmd = AdjustCreditCommand(agent_id="agent_001", amount=10.0, reason="mission_reward")
        assert cmd.agent_id == "agent_001"
        assert cmd.amount == 10.0
        assert cmd.reason == "mission_reward"

    def test_update_agent_command(self):
        """Test UpdateAgentCommand creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import UpdateAgentCommand

        # UpdateAgentCommand uses individual optional fields, not an 'updates' dict
        cmd = UpdateAgentCommand(
            agent_id="agent_001", model="gpt-4-turbo", name="Updated Commander"
        )
        assert cmd.agent_id == "agent_001"
        assert cmd.model == "gpt-4-turbo"
        assert cmd.name == "Updated Commander"
        # Unset fields default to None
        assert cmd.temperature is None


class TestQueryClasses:
    """Tests for CQRS Query dataclasses — using actual signatures"""

    def test_get_agent_query(self):
        """Test GetAgentQuery creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import GetAgentQuery

        query = GetAgentQuery(agent_id="agent_001")
        assert query.agent_id == "agent_001"

    def test_list_agents_query(self):
        """Test ListAgentsQuery creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import ListAgentsQuery

        query = ListAgentsQuery(tenant_id="tenant_1", limit=10, offset=0)
        assert query.tenant_id == "tenant_1"
        assert query.limit == 10

    def test_list_agents_query_defaults(self):
        """Test ListAgentsQuery default values"""
        from backend.core.cqrs.cqrs_impl import ListAgentsQuery

        query = ListAgentsQuery(tenant_id="tenant_1")
        assert query.limit == 100
        assert query.offset == 0

    def test_get_mission_query(self):
        """Test GetMissionQuery creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import GetMissionQuery

        query = GetMissionQuery(mission_id="mission_001")
        assert query.mission_id == "mission_001"

    def test_list_missions_query(self):
        """Test ListMissionsQuery creation with actual signature"""
        from backend.core.cqrs.cqrs_impl import ListMissionsQuery

        query = ListMissionsQuery(status="active", limit=20, offset=0)
        assert query.status == "active"
        assert query.limit == 20

    def test_list_missions_query_all_optional(self):
        """Test ListMissionsQuery with all optional fields"""
        from backend.core.cqrs.cqrs_impl import ListMissionsQuery

        query = ListMissionsQuery()
        assert query.agent_id is None
        assert query.status is None
        assert query.limit == 100


class TestCommandBus:
    """Tests for the CQRS CommandBus"""

    @pytest.mark.asyncio
    async def test_command_bus_dispatch_to_handler(self):
        """Test that CommandBus dispatches commands to registered handlers"""
        from backend.core.cqrs.cqrs_impl import CommandBus, CreateAgentCommand

        bus = CommandBus()
        mock_handler = MagicMock()
        mock_handler.handle = AsyncMock(return_value="agent_001")
        bus.register(CreateAgentCommand, mock_handler)

        cmd = CreateAgentCommand(
            tenant_id="tenant_1",
            name="Test",
            model="gpt-4",
            capabilities=[],
            system_prompt="You are an agent.",
        )
        result = await bus.dispatch(cmd)
        mock_handler.handle.assert_called_once_with(cmd)
        assert result == "agent_001"

    @pytest.mark.asyncio
    async def test_command_bus_unregistered_raises(self):
        """Test that dispatching an unregistered command raises an exception"""
        from backend.core.cqrs.cqrs_impl import CommandBus, CreateAgentCommand

        bus = CommandBus()
        cmd = CreateAgentCommand(
            tenant_id="tenant_1",
            name="Test",
            model="gpt-4",
            capabilities=[],
            system_prompt="You are an agent.",
        )
        with pytest.raises(Exception):
            await bus.dispatch(cmd)

    def test_command_bus_register(self):
        """Test that CommandBus.register stores the handler"""
        from backend.core.cqrs.cqrs_impl import CommandBus, CreateAgentCommand

        bus = CommandBus()
        mock_handler = MagicMock()
        bus.register(CreateAgentCommand, mock_handler)
        assert CreateAgentCommand in bus._handlers


class TestQueryBus:
    """Tests for the CQRS QueryBus"""

    @pytest.mark.asyncio
    async def test_query_bus_dispatch_to_handler(self):
        """Test that QueryBus dispatches queries to registered handlers"""
        from backend.core.cqrs.cqrs_impl import QueryBus, GetAgentQuery

        bus = QueryBus()
        expected_result = {"agent_id": "agent_001", "name": "TestAgent"}
        mock_handler = MagicMock()
        mock_handler.handle = AsyncMock(return_value=expected_result)
        bus.register(GetAgentQuery, mock_handler)

        query = GetAgentQuery(agent_id="agent_001")
        result = await bus.dispatch(query)
        mock_handler.handle.assert_called_once_with(query)
        assert result == expected_result

    def test_query_bus_register(self):
        """Test that QueryBus.register stores the handler"""
        from backend.core.cqrs.cqrs_impl import QueryBus, GetAgentQuery

        bus = QueryBus()
        mock_handler = MagicMock()
        bus.register(GetAgentQuery, mock_handler)
        assert GetAgentQuery in bus._handlers


# ============================================================================
# Saga Orchestration Tests
# ============================================================================


class TestSagaOrchestrator:
    """Tests for the SagaOrchestrator engine"""

    def _make_orchestrator(self):
        from backend.core.saga.saga_orchestrator import SagaOrchestrator
        from backend.core.event_sourcing.event_store_impl import EventStore

        mock_event_store = MagicMock(spec=EventStore)
        mock_event_store.append = AsyncMock()
        return SagaOrchestrator(event_store=mock_event_store)

    def test_create_saga(self):
        """Test creating a saga definition"""

        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga", context={"key": "value"})
        assert saga.name == "test_saga"
        assert saga.context["key"] == "value"
        assert saga.saga_id is not None
        assert len(saga.steps) == 0

    def test_create_saga_empty_context(self):
        """Test creating a saga with no context defaults to empty dict"""
        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga")
        assert saga.context == {}

    def test_add_step(self):
        """Test adding steps to a saga"""
        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga", context={})

        async def step_fn(ctx):
            return ctx

        async def comp_fn(ctx):
            return ctx

        step = orchestrator.add_step(saga=saga, name="step_1", action=step_fn, compensation=comp_fn)
        assert len(saga.steps) == 1
        assert saga.steps[0].name == "step_1"
        assert step.step_id is not None

    def test_add_multiple_steps(self):
        """Test adding multiple steps maintains order"""
        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga", context={})

        async def noop(ctx):
            return ctx

        orchestrator.add_step(saga, "step_1", noop, None)
        orchestrator.add_step(saga, "step_2", noop, None)
        orchestrator.add_step(saga, "step_3", noop, None)

        assert len(saga.steps) == 3
        assert saga.steps[0].name == "step_1"
        assert saga.steps[1].name == "step_2"
        assert saga.steps[2].name == "step_3"

    @pytest.mark.asyncio
    async def test_execute_successful_saga(self):
        """Test executing a saga where all steps succeed"""
        from backend.core.saga.saga_orchestrator import SagaStatus

        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga", context={"value": 0})

        async def step_1(ctx):
            ctx["value"] += 1
            return ctx

        async def step_2(ctx):
            ctx["value"] += 1
            return ctx

        orchestrator.add_step(saga, "step_1", step_1, None)
        orchestrator.add_step(saga, "step_2", step_2, None)

        success = await orchestrator.execute(saga)
        assert success is True
        assert saga.status == SagaStatus.COMPLETED
        assert saga.context["value"] == 2

    @pytest.mark.asyncio
    async def test_execute_saga_with_compensation(self):
        """Test that compensation runs when a step fails"""
        from backend.core.saga.saga_orchestrator import SagaStatus

        orchestrator = self._make_orchestrator()
        compensation_called = []

        saga = orchestrator.create_saga(name="test_saga", context={"value": 0})

        async def step_1(ctx):
            ctx["value"] += 1
            return ctx

        async def compensate_step_1(ctx, step_result):
            # Compensation receives (context, step_result) per SagaOrchestrator._compensate_step
            compensation_called.append("step_1_compensated")
            ctx["value"] -= 1
            return ctx

        async def step_2_fails(ctx):
            raise ValueError("Step 2 failed intentionally")

        orchestrator.add_step(saga, "step_1", step_1, compensate_step_1)
        orchestrator.add_step(saga, "step_2", step_2_fails, None)

        success = await orchestrator.execute(saga)
        assert success is False
        assert saga.status == SagaStatus.COMPENSATED
        assert "step_1_compensated" in compensation_called

    @pytest.mark.asyncio
    async def test_get_saga_by_id(self):
        """Test retrieving a saga by ID"""
        orchestrator = self._make_orchestrator()
        saga = orchestrator.create_saga(name="test_saga", context={})
        retrieved = orchestrator.get_saga(saga.saga_id)
        assert retrieved is not None
        assert retrieved.saga_id == saga.saga_id

    def test_get_nonexistent_saga_returns_none(self):
        """Test that getting a non-existent saga returns None"""
        orchestrator = self._make_orchestrator()
        result = orchestrator.get_saga("nonexistent_id")
        assert result is None


class TestMissionExecutionSaga:
    """Tests for the MissionExecutionSaga"""

    def _make_saga(self):
        from backend.core.saga.saga_orchestrator import (
            MissionExecutionSaga,
            SagaOrchestrator,
        )
        from backend.core.event_sourcing.event_store_impl import EventStore

        mock_event_store = MagicMock(spec=EventStore)
        mock_event_store.append = AsyncMock()
        orchestrator = SagaOrchestrator(event_store=mock_event_store)

        mock_marketplace = MagicMock()
        mock_marketplace.charge = AsyncMock(return_value={"balance": 98.5})
        mock_marketplace.get_balance = AsyncMock(return_value={"balance": 100.0})
        mock_marketplace.reward = AsyncMock(return_value={"balance": 101.0})

        mock_executor = MagicMock()
        mock_executor.execute_mission = AsyncMock(
            return_value={
                "status": "completed",
                "result": {"output": "success"},
                "cost": 1.5,
            }
        )

        mock_db = MagicMock()

        return MissionExecutionSaga(
            orchestrator=orchestrator,
            marketplace=mock_marketplace,
            mission_executor=mock_executor,
            db_session=mock_db,
        )

    def test_mission_saga_creation(self):
        """Test MissionExecutionSaga can be instantiated"""
        saga = self._make_saga()
        assert saga is not None
        assert saga.marketplace is not None
        assert saga.mission_executor is not None

    @pytest.mark.asyncio
    async def test_mission_saga_execute_returns_bool(self):
        """Test MissionExecutionSaga.execute returns a boolean"""
        saga = self._make_saga()
        result = await saga.execute(
            mission_id="mission_001",
            agent_id="agent_001",
            tenant_id="tenant_1",
            user_id="user_1",
            goal="Analyze market trends",
            estimated_cost=1.5,
        )
        assert isinstance(result, bool)


class TestAgentCreationSaga:
    """Tests for the AgentCreationSaga"""

    def _make_saga(self):
        from backend.core.saga.saga_orchestrator import (
            AgentCreationSaga,
            SagaOrchestrator,
        )
        from backend.core.event_sourcing.event_store_impl import EventStore

        mock_event_store = MagicMock(spec=EventStore)
        mock_event_store.append = AsyncMock()
        orchestrator = SagaOrchestrator(event_store=mock_event_store)

        mock_marketplace = MagicMock()
        mock_marketplace.reward = AsyncMock(return_value={"balance": 1000.0})

        mock_db = MagicMock()

        return AgentCreationSaga(
            orchestrator=orchestrator, marketplace=mock_marketplace, db_session=mock_db
        )

    def test_agent_saga_creation(self):
        """Test AgentCreationSaga can be instantiated"""
        saga = self._make_saga()
        assert saga is not None
        assert saga.marketplace is not None

    @pytest.mark.asyncio
    async def test_agent_saga_execute_returns_bool(self):
        """Test AgentCreationSaga.execute returns a boolean"""
        saga = self._make_saga()
        result = await saga.execute(
            agent_id="agent_001",
            tenant_id="tenant_1",
            name="Test Commander",
            agent_type="commander",
            model="gpt-4",
            config={"temperature": 0.7},
            initial_budget=1000.0,
        )
        assert isinstance(result, bool)


# ============================================================================
# CQRS Setup Module Tests
# ============================================================================


class TestCQRSSetupModule:
    """Tests for the CQRS setup module"""

    def test_command_bus_importable_from_cqrs_impl(self):
        """Test that CommandBus can be imported from cqrs_impl"""
        from backend.core.cqrs.cqrs_impl import CommandBus

        assert CommandBus is not None

    def test_query_bus_importable_from_cqrs_impl(self):
        """Test that QueryBus can be imported from cqrs_impl"""
        from backend.core.cqrs.cqrs_impl import QueryBus

        assert QueryBus is not None

    def test_setup_cqrs_function_exists(self):
        """Test that setup_cqrs function exists and is callable"""
        from backend.core.cqrs.setup import setup_cqrs

        assert callable(setup_cqrs)

    def test_get_command_bus_raises_before_setup(self):
        """Test that get_command_bus raises RuntimeError before setup"""
        from backend.core.cqrs.setup import get_command_bus, teardown_cqrs

        teardown_cqrs()  # Ensure clean state
        with pytest.raises(RuntimeError, match="CQRS buses not initialised"):
            get_command_bus()

    def test_get_query_bus_raises_before_setup(self):
        """Test that get_query_bus raises RuntimeError before setup"""
        from backend.core.cqrs.setup import get_query_bus, teardown_cqrs

        teardown_cqrs()  # Ensure clean state
        with pytest.raises(RuntimeError, match="CQRS buses not initialised"):
            get_query_bus()

    def test_teardown_cqrs_resets_state(self):
        """Test that teardown_cqrs resets the bus singletons"""
        from backend.core.cqrs.setup import teardown_cqrs, get_command_bus

        teardown_cqrs()
        with pytest.raises(RuntimeError):
            get_command_bus()


# ============================================================================
# Event Store Module Re-export Tests
# ============================================================================


class TestEventStoreModuleReexports:
    """Tests for the event_store.py module re-exports"""

    def test_event_importable_from_event_store(self):
        """Test that Event can be imported from event_store module"""
        from backend.core.event_sourcing.event_store import Event

        assert Event is not None

    def test_event_type_importable_from_event_store(self):
        """Test that EventType can be imported from event_store module"""
        from backend.core.event_sourcing.event_store import EventType

        assert EventType is not None

    def test_event_store_class_importable(self):
        """Test that EventStore class can be imported from event_store module"""
        from backend.core.event_sourcing.event_store import EventStore

        assert EventStore is not None

    def test_snapshot_store_importable(self):
        """Test that SnapshotStore can be imported from event_store module"""
        from backend.core.event_sourcing.event_store import SnapshotStore

        assert SnapshotStore is not None

    def test_snapshot_importable(self):
        """Test that Snapshot can be imported from event_store module"""
        from backend.core.event_sourcing.event_store import Snapshot

        assert Snapshot is not None

    def test_concurrency_error_importable(self):
        """Test that ConcurrencyError can be imported"""
        from backend.core.event_sourcing.event_store import ConcurrencyError

        assert ConcurrencyError is not None

    def test_event_store_error_importable(self):
        """Test that EventStoreError can be imported"""
        from backend.core.event_sourcing.event_store import EventStoreError

        assert EventStoreError is not None
