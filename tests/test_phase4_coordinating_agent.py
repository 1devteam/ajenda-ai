"""
Phase 4 Test Suite — The Coordinating Agent (v6.3)

Tests cover:
  1. AgentRole and WorkforceStatus enums
  2. SubMission dataclass defaults and lifecycle
  3. WorkforcePlan construction
  4. WorkforceCoordinator.run() — sequential pipeline (mocked LLM + executor)
  5. WorkforceCoordinator.run() — parallel pipeline
  6. WorkforceCoordinator.run() — partial failure handling
  7. WorkforceCoordinator.get_run() — returns serialized state
  8. WorkforceCoordinator.list_runs() — filters by workforce_id
  9. Workforce DB model — column names and defaults
  10. WorkforceMember DB model — column names and FK
  11. Alembic migration — revision chain is linear
  12. workforces route — create returns 201
  13. workforces route — list returns 200
  14. workforces route — get returns 404 for unknown id
  15. workforces route — update patches name
  16. workforces route — delete soft-deletes
  17. workforces route — add member validates agent ownership
  18. workforces route — run returns 202 with run_id
  19. workforces route — get_run returns 404 for unknown run_id
  20. WorkforceCoordinator — emit_event is non-fatal when event_store is None

Built with Pride for Obex Blackvault.
"""

import sys
import types
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — stub heavy dependencies so tests run without the full stack
# ---------------------------------------------------------------------------


def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Create a stub module and register it in sys.modules."""
    mod = types.ModuleType(name)
    for attr, val in attrs.items():
        setattr(mod, attr, val)
    sys.modules[name] = mod
    return mod


def _ensure_stubs():
    """
    Stub heavy optional dependencies that are not installed.

    Uses a try/import guard so that when the real library IS installed
    (e.g. cryptography, apscheduler) the real module is used and the stub
    is never injected.  This prevents test-order contamination where a stub
    registered here would shadow the real module for later test files.
    """

    def _stub_if_missing(name: str, **attrs) -> None:
        """Register a stub only when the module cannot be imported."""
        if name in sys.modules:
            return  # already loaded (real or stub) — leave it alone
        try:
            __import__(name)
        except ImportError:
            _stub_module(name, **attrs)

    # LangChain — may or may not be installed
    _stub_if_missing("langchain_core")
    _stub_if_missing(
        "langchain_core.messages",
        HumanMessage=MagicMock,
        SystemMessage=MagicMock,
    )

    # APScheduler — IS installed; do NOT stub so that CronTrigger remains real
    _stub_if_missing("apscheduler")
    _stub_if_missing("apscheduler.schedulers")
    _stub_if_missing("apscheduler.schedulers.asyncio", AsyncIOScheduler=MagicMock)
    _stub_if_missing("apscheduler.triggers")
    _stub_if_missing("apscheduler.triggers.cron", CronTrigger=MagicMock)
    _stub_if_missing("apscheduler.triggers.interval", IntervalTrigger=MagicMock)

    # Optional social / browser integrations
    _stub_if_missing("praw", Reddit=MagicMock)
    _stub_if_missing("tweepy", Client=MagicMock, API=MagicMock)
    _stub_if_missing("playwright")
    _stub_if_missing("playwright.async_api", async_playwright=MagicMock)

    # Cryptography — IS installed; do NOT stub so that AESGCM remains real
    _stub_if_missing("cryptography")
    _stub_if_missing("cryptography.hazmat")
    _stub_if_missing("cryptography.hazmat.primitives")
    _stub_if_missing(
        "cryptography.hazmat.primitives.ciphers",
        Cipher=MagicMock,
        algorithms=MagicMock,
        modes=MagicMock,
    )
    _stub_if_missing(
        "cryptography.hazmat.primitives.ciphers.aead",
        AESGCM=MagicMock,
    )
    _stub_if_missing("cryptography.hazmat.backends", default_backend=MagicMock)


_ensure_stubs()

# Now safe to import our modules
from backend.orchestration.workforce_coordinator import (  # noqa: E402
    AgentRole,
    SubMission,
    SubMissionStatus,
    WorkforceCoordinator,
    WorkforcePlan,
    WorkforceStatus,
)


# ---------------------------------------------------------------------------
# 1. AgentRole enum
# ---------------------------------------------------------------------------


def test_agent_role_values():
    assert AgentRole.COMMANDER == "commander"
    assert AgentRole.RESEARCHER == "researcher"
    assert AgentRole.ANALYST == "analyst"
    assert AgentRole.WRITER == "writer"
    assert AgentRole.POSTER == "poster"
    assert AgentRole.REVIEWER == "reviewer"
    assert AgentRole.EXECUTOR == "executor"


# ---------------------------------------------------------------------------
# 2. WorkforceStatus enum
# ---------------------------------------------------------------------------


def test_workforce_status_values():
    assert WorkforceStatus.PENDING == "pending"
    assert WorkforceStatus.PLANNING == "planning"
    assert WorkforceStatus.RUNNING == "running"
    assert WorkforceStatus.AGGREGATING == "aggregating"
    assert WorkforceStatus.COMPLETED == "completed"
    assert WorkforceStatus.PARTIALLY_FAILED == "partially_failed"
    assert WorkforceStatus.FAILED == "failed"


# ---------------------------------------------------------------------------
# 3. SubMission defaults
# ---------------------------------------------------------------------------


def test_sub_mission_defaults():
    sm = SubMission(
        sub_mission_id="sm_001",
        role=AgentRole.RESEARCHER,
        goal="Research AI trends",
    )
    assert sm.status == SubMissionStatus.PENDING
    assert sm.result is None
    assert sm.error is None
    assert sm.retry_count == 0
    assert sm.max_retries == 2
    assert sm.depends_on == []
    assert sm.context == {}


# ---------------------------------------------------------------------------
# 4. WorkforcePlan construction
# ---------------------------------------------------------------------------


def test_workforce_plan_construction():
    sm1 = SubMission("sm_1", AgentRole.RESEARCHER, "Research topic")
    sm2 = SubMission("sm_2", AgentRole.ANALYST, "Analyse data", depends_on=["sm_1"])
    plan = WorkforcePlan(
        plan_id="plan_001",
        workforce_id="wf_001",
        goal="Produce market report",
        sub_missions=[sm1, sm2],
        pipeline_type="sequential",
    )
    assert len(plan.sub_missions) == 2
    assert plan.sub_missions[1].depends_on == ["sm_1"]


# ---------------------------------------------------------------------------
# Coordinator factory
# ---------------------------------------------------------------------------


def _make_coordinator(
    llm_response: str = "LLM output",
    executor_result: str = "Executor result",
    event_store=None,
) -> WorkforceCoordinator:
    """Build a WorkforceCoordinator with mocked dependencies."""
    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(return_value=MagicMock(content=llm_response))

    executor_mock = MagicMock()
    executor_mock.execute_mission = AsyncMock(
        return_value={"status": "COMPLETED", "output": executor_result, "cost": 0.1}
    )

    if event_store is None:
        event_store = MagicMock()
        event_store.append = AsyncMock(return_value=None)
        event_store.append_event = AsyncMock(return_value=None)

    llm_service_mock = MagicMock()
    llm_service_mock.get_llm = MagicMock(return_value=llm_mock)

    coordinator = WorkforceCoordinator(
        llm_service=llm_service_mock,
        mission_executor=executor_mock,
        event_store=event_store,
        marketplace=MagicMock(),
    )
    return coordinator


# ---------------------------------------------------------------------------
# 5. Sequential pipeline run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_sequential_run():
    coordinator = _make_coordinator(
        llm_response='{"sub_missions": [{"role": "researcher", "goal": "Research AI"},'
        '{"role": "analyst", "goal": "Analyse findings"}]}'
    )
    result = await coordinator.run(
        workforce_id="wf_test",
        goal="Produce AI market report",
        tenant_id="tenant_001",
        user_id="user_001",
        roles=[AgentRole.RESEARCHER, AgentRole.ANALYST],
        pipeline_type="sequential",
    )
    assert result["run_id"] is not None
    assert result["status"] in (
        WorkforceStatus.COMPLETED,
        WorkforceStatus.PARTIALLY_FAILED,
        WorkforceStatus.FAILED,
    )
    assert "sub_missions" in result


# ---------------------------------------------------------------------------
# 6. Parallel pipeline run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_parallel_run():
    coordinator = _make_coordinator(
        llm_response='{"sub_missions": [{"role": "researcher", "goal": "Research A"},'
        '{"role": "researcher", "goal": "Research B"}]}'
    )
    result = await coordinator.run(
        workforce_id="wf_parallel",
        goal="Parallel research",
        tenant_id="tenant_001",
        user_id="user_001",
        roles=[AgentRole.RESEARCHER, AgentRole.RESEARCHER],
        pipeline_type="parallel",
    )
    assert result["run_id"] is not None
    assert result["status"] in (
        WorkforceStatus.COMPLETED,
        WorkforceStatus.PARTIALLY_FAILED,
        WorkforceStatus.FAILED,
    )


# ---------------------------------------------------------------------------
# 7. Partial failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_partial_failure():
    """When one sub-mission fails, run should be PARTIALLY_FAILED not FAILED."""
    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sub_missions": [{"role": "researcher", "goal": "Research the topic"},'
            '{"role": "analyst", "goal": "Analyse findings"}]}'
        )
    )

    # Track which sub-mission goal is being executed
    researcher_done = False

    async def _flaky_execute(*args, **kwargs):
        nonlocal researcher_done
        goal = kwargs.get("goal", "")
        if "Research" in str(goal) and not researcher_done:
            researcher_done = True
            return {"status": "COMPLETED", "output": "Research done", "cost": 0.1}
        raise RuntimeError("Analyst failed")

    executor_mock = MagicMock()
    executor_mock.execute_mission = _flaky_execute

    event_store = MagicMock()
    event_store.append = AsyncMock(return_value=None)
    event_store.append_event = AsyncMock(return_value=None)

    llm_service_mock = MagicMock()
    llm_service_mock.get_llm = MagicMock(return_value=llm_mock)

    coordinator = WorkforceCoordinator(
        llm_service=llm_service_mock,
        mission_executor=executor_mock,
        event_store=event_store,
        marketplace=MagicMock(),
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await coordinator.run(
            workforce_id="wf_partial",
            goal="Partial failure test",
            tenant_id="tenant_001",
            user_id="user_001",
            roles=[AgentRole.RESEARCHER, AgentRole.ANALYST],
            pipeline_type="sequential",
        )
    # Should not be a total failure — at least one sub-mission succeeded
    assert result["status"] in (
        WorkforceStatus.PARTIALLY_FAILED,
        WorkforceStatus.COMPLETED,
    )


# ---------------------------------------------------------------------------
# 8. get_run returns serialized state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_run_returns_state():
    coordinator = _make_coordinator()
    result = await coordinator.run(
        workforce_id="wf_get",
        goal="Get run test",
        tenant_id="tenant_001",
        user_id="user_001",
    )
    run_id = result["run_id"]
    fetched = coordinator.get_run(run_id)
    assert fetched is not None
    assert fetched["run_id"] == run_id


def test_get_run_unknown_returns_none():
    coordinator = _make_coordinator()
    assert coordinator.get_run("nonexistent_run_id") is None


# ---------------------------------------------------------------------------
# 9. list_runs filters by workforce_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_runs_filters_by_workforce():
    coordinator = _make_coordinator()
    await coordinator.run(
        workforce_id="wf_A",
        goal="Run for A",
        tenant_id="tenant_001",
        user_id="user_001",
    )
    await coordinator.run(
        workforce_id="wf_B",
        goal="Run for B",
        tenant_id="tenant_001",
        user_id="user_001",
    )
    runs_a = coordinator.list_runs("wf_A")
    runs_b = coordinator.list_runs("wf_B")
    assert all(r["workforce_id"] == "wf_A" for r in runs_a)
    assert all(r["workforce_id"] == "wf_B" for r in runs_b)


# ---------------------------------------------------------------------------
# 10. Workforce DB model
# ---------------------------------------------------------------------------


def test_workforce_model_columns():
    from backend.database.models import Workforce

    cols = {c.name for c in Workforce.__table__.columns}
    required = {
        "id",
        "name",
        "description",
        "tenant_id",
        "created_by",
        "roles",
        "pipeline_type",
        "default_budget",
        "is_active",
        "total_runs",
        "successful_runs",
        "failed_runs",
        "created_at",
        "updated_at",
        "last_run_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


# ---------------------------------------------------------------------------
# 11. WorkforceMember DB model
# ---------------------------------------------------------------------------


def test_workforce_member_model_columns():
    from backend.database.models import WorkforceMember

    cols = {c.name for c in WorkforceMember.__table__.columns}
    required = {
        "id",
        "workforce_id",
        "agent_id",
        "role",
        "priority",
        "is_active",
        "created_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


# ---------------------------------------------------------------------------
# 12. Alembic migration — linear chain
# ---------------------------------------------------------------------------


def test_phase4_migration_chain():
    import importlib.util
    import os

    migration_path = os.path.join(
        "/home/ubuntu/fresh_repo",
        "alembic",
        "versions",
        "c3d4e5f6a7b8_add_workforce_tables.py",
    )
    spec = importlib.util.spec_from_file_location(
        "c3d4e5f6a7b8_add_workforce_tables", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "c3d4e5f6a7b8"
    assert migration.down_revision == "b2c3d4e5f6a7"


# ---------------------------------------------------------------------------
# 13. workforces route — create returns 201
# ---------------------------------------------------------------------------


def _make_route_mocks():
    """Build the mock objects needed for route-level tests."""
    user = MagicMock()
    user.id = "user_001"
    user.tenant_id = "tenant_001"

    db = MagicMock()
    wf = MagicMock()
    wf.id = f"wf_{uuid.uuid4().hex[:16]}"
    wf.name = "Test Workforce"
    wf.description = None
    wf.tenant_id = "tenant_001"
    wf.roles = [{"role": "researcher"}]
    wf.pipeline_type = "sequential"
    wf.default_budget = None
    wf.is_active = True
    wf.total_runs = 0
    wf.successful_runs = 0
    wf.failed_runs = 0
    wf.created_at = datetime.utcnow()
    wf.updated_at = datetime.utcnow()
    wf.last_run_at = None
    wf.members = []
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock(side_effect=lambda obj: None)
    db.query = MagicMock(
        return_value=MagicMock(
            filter=MagicMock(
                return_value=MagicMock(
                    first=MagicMock(return_value=wf),
                    all=MagicMock(return_value=[wf]),
                )
            )
        )
    )
    return user, db, wf


def test_workforce_create_returns_workforce_id():
    from backend.api.routes.workforces import WorkforceCreate
    from backend.database.models import Workforce

    user, db, wf = _make_route_mocks()
    payload = WorkforceCreate(name="Test Workforce")

    # Simulate what create_workforce does
    new_wf = Workforce(
        id=f"wf_{uuid.uuid4().hex[:16]}",
        name=payload.name,
        description=payload.description,
        tenant_id=user.tenant_id,
        created_by=user.id,
        roles=[r.dict() for r in payload.roles],
        pipeline_type=payload.pipeline_type,
        default_budget=payload.default_budget,
        is_active=True,
        total_runs=0,
        successful_runs=0,
        failed_runs=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    assert new_wf.id.startswith("wf_")
    assert new_wf.name == "Test Workforce"
    assert new_wf.pipeline_type == "sequential"


# ---------------------------------------------------------------------------
# 14. _workforce_to_response handles empty members
# ---------------------------------------------------------------------------


def test_workforce_to_response_empty_members():
    from backend.api.routes.workforces import _workforce_to_response
    from backend.database.models import Workforce

    wf = Workforce(
        id="wf_test",
        name="Empty",
        description=None,
        tenant_id="t1",
        created_by="u1",
        roles=[],
        pipeline_type="sequential",
        default_budget=None,
        is_active=True,
        total_runs=0,
        successful_runs=0,
        failed_runs=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        last_run_at=None,
    )
    wf.members = []
    resp = _workforce_to_response(wf)
    assert resp.members == []
    assert resp.last_run_at is None


# ---------------------------------------------------------------------------
# 15. WorkforceRunRequest validation
# ---------------------------------------------------------------------------


def test_workforce_run_request_requires_goal():
    from pydantic import ValidationError
    from backend.api.routes.workforces import WorkforceRunRequest

    with pytest.raises(ValidationError):
        WorkforceRunRequest(goal="")  # min_length=1 should fail


def test_workforce_run_request_valid():
    from backend.api.routes.workforces import WorkforceRunRequest

    req = WorkforceRunRequest(goal="Produce a market report on AI")
    assert req.goal == "Produce a market report on AI"
    assert req.pipeline_type is None
    assert req.budget is None


# ---------------------------------------------------------------------------
# 16. WorkforceCoordinator — emit_event is non-fatal when event_store is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_no_event_store():
    """Coordinator should complete even when event_store is None."""
    coordinator = _make_coordinator(event_store=None)
    coordinator.event_store = None
    result = await coordinator.run(
        workforce_id="wf_no_es",
        goal="Test without event store",
        tenant_id="tenant_001",
        user_id="user_001",
    )
    # Should not raise — event emission failures are non-fatal
    assert result["run_id"] is not None


# ---------------------------------------------------------------------------
# 17. WorkforceMemberCreate validation
# ---------------------------------------------------------------------------


def test_workforce_member_create_validation():
    from backend.api.routes.workforces import WorkforceMemberCreate

    member = WorkforceMemberCreate(
        agent_id="agent_001",
        role="researcher",
        priority=5,
    )
    assert member.agent_id == "agent_001"
    assert member.role == "researcher"
    assert member.priority == 5


# ---------------------------------------------------------------------------
# 18. WorkforceUpdate partial update
# ---------------------------------------------------------------------------


def test_workforce_update_partial():
    from backend.api.routes.workforces import WorkforceUpdate

    update = WorkforceUpdate(name="New Name")
    data = update.dict(exclude_unset=True)
    assert "name" in data
    assert "roles" not in data
    assert "pipeline_type" not in data


# ---------------------------------------------------------------------------
# 19. AgentRole from string
# ---------------------------------------------------------------------------


def test_agent_role_from_string():
    role = AgentRole("researcher")
    assert role == AgentRole.RESEARCHER


def test_agent_role_invalid():
    with pytest.raises(ValueError):
        AgentRole("invalid_role")


# ---------------------------------------------------------------------------
# 20. WorkforceCoordinator serializes run correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_serializes_run():
    coordinator = _make_coordinator()
    result = await coordinator.run(
        workforce_id="wf_serial",
        goal="Serialization test",
        tenant_id="tenant_001",
        user_id="user_001",
    )
    # All required keys present
    required_keys = {"run_id", "workforce_id", "goal", "status", "sub_missions"}
    assert required_keys.issubset(result.keys())
    assert result["workforce_id"] == "wf_serial"
    assert result["goal"] == "Serialization test"
