from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import Mission, MissionPlan, build_mission_plan_contract_metadata
from backend.repositories.mission_plan_repository import MissionPlanRepository


def _mission(*, tenant_id: str | None = None, mission_id: uuid.UUID | None = None) -> Mission:
    return Mission(
        id=mission_id or uuid.uuid4(),
        tenant_id=tenant_id or str(uuid.uuid4()),
        objective="Recover stale qualified opportunities.",
    )


def test_create_plan_for_tenant_mission_flushes_and_refreshes() -> None:
    mission = _mission()
    metadata = build_mission_plan_contract_metadata(objectives=["Recover stale opportunities."])
    session = MagicMock()
    session.scalar.return_value = None

    result = MissionPlanRepository(session).create_or_get_active_for_mission(
        mission=mission,
        metadata_json=metadata,
    )

    assert isinstance(result, MissionPlan)
    assert result.tenant_id == mission.tenant_id
    assert result.mission_id == mission.id
    assert result.status == MissionPlanStatus.DRAFT.value
    assert result.metadata_json == metadata
    session.add.assert_called_once_with(result)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(result)


def test_retrieve_active_plan_by_mission_and_tenant_uses_tenant_scope() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    plan = MissionPlan(tenant_id=tenant_id, mission_id=mission_id, metadata_json={})
    session = MagicMock()
    session.scalar.return_value = plan

    result = MissionPlanRepository(session).get_active_for_mission(mission_id=mission_id, tenant_id=tenant_id)

    assert result is plan
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mission_plans.mission_id" in compiled
    assert "mission_plans.tenant_id" in compiled
    assert tenant_id in compiled
    assert "draft" in compiled
    assert "ready" in compiled


def test_foreign_tenant_cannot_read_plan_because_lookup_is_tenant_scoped() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = None

    result = MissionPlanRepository(session).get_active_for_mission(mission_id=mission_id, tenant_id=tenant_id)

    assert result is None
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert tenant_id in compiled


def test_idempotent_create_returns_existing_active_plan_without_duplicate() -> None:
    mission = _mission()
    existing = MissionPlan(tenant_id=mission.tenant_id, mission_id=mission.id, metadata_json={"existing": True})
    session = MagicMock()
    session.scalar.return_value = existing

    result = MissionPlanRepository(session).create_or_get_active_for_mission(
        mission=mission,
        metadata_json=build_mission_plan_contract_metadata(objectives=["New metadata ignored."]),
    )

    assert result is existing
    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.refresh.assert_not_called()


def test_duplicate_create_race_reloads_existing_active_plan_after_integrity_conflict() -> None:
    mission = _mission()
    existing = MissionPlan(tenant_id=mission.tenant_id, mission_id=mission.id, metadata_json={"winner": True})
    session = MagicMock()
    session.scalar.side_effect = [None, existing]
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))

    result = MissionPlanRepository(session).create_or_get_active_for_mission(
        mission=mission,
        metadata_json=build_mission_plan_contract_metadata(),
    )

    assert result is existing
    session.rollback.assert_called_once_with()


def test_duplicate_create_race_reraises_when_no_active_plan_can_be_reloaded() -> None:
    mission = _mission()
    session = MagicMock()
    session.scalar.side_effect = [None, None]
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))

    with pytest.raises(IntegrityError):
        MissionPlanRepository(session).create_or_get_active_for_mission(
            mission=mission,
            metadata_json=build_mission_plan_contract_metadata(),
        )


def test_replace_active_plan_updates_metadata_and_transitions_status() -> None:
    mission = _mission()
    plan = MissionPlan(
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        status=MissionPlanStatus.DRAFT.value,
        metadata_json={"existing": True},
    )
    session = MagicMock()
    updated_metadata = build_mission_plan_contract_metadata(objectives=["Updated objective."])

    result = MissionPlanRepository(session).replace_active_plan(
        plan=plan,
        metadata_json=updated_metadata,
        status=MissionPlanStatus.READY.value,
    )

    assert result is plan
    assert result.status == MissionPlanStatus.READY.value
    assert result.metadata_json == updated_metadata
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(plan)


def test_replace_active_plan_rejects_invalid_status_transition() -> None:
    mission = _mission()
    plan = MissionPlan(
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        status=MissionPlanStatus.READY.value,
        metadata_json={},
    )
    session = MagicMock()

    with pytest.raises(ValueError, match="mission plan status transition not allowed"):
        MissionPlanRepository(session).replace_active_plan(
            plan=plan,
            metadata_json=build_mission_plan_contract_metadata(),
            status=MissionPlanStatus.DRAFT.value,
        )


def test_idempotent_create_with_different_status_returns_existing_plan_unchanged() -> None:
    mission = _mission()
    existing = MissionPlan(
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        status=MissionPlanStatus.DRAFT.value,
        metadata_json={"existing": True},
    )
    session = MagicMock()
    session.scalar.return_value = existing

    result = MissionPlanRepository(session).create_or_get_active_for_mission(
        mission=mission,
        status=MissionPlanStatus.READY.value,
        metadata_json=build_mission_plan_contract_metadata(objectives=["Attempted replacement."]),
    )

    assert result is existing
    assert result.status == MissionPlanStatus.DRAFT.value
    assert result.metadata_json == {"existing": True}
    session.add.assert_not_called()
    session.flush.assert_not_called()
