"""Durability and locking guarantees for mission composition proposals."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import Mission, MissionPlan
from backend.repositories.mission_composition_proposal_repository import MissionCompositionProposalRepository
from backend.services.mission_composition.proposal_store import (
    ProposalStoreRecordError,
    ProposalStoreUnavailableError,
    clear_proposals_for_tests,
    get_proposal,
    get_proposal_for_confirmation,
    put_proposal,
)
from backend.services.mission_composition.service import MissionCompositionService
from tests.mission_interpreter_fakes import StaticMissionInterpreter, ready_intent


def _record():  # type: ignore[no-untyped-def]
    instruction = "Find roofing companies in Austin."
    record = MissionCompositionService(interpreter=StaticMissionInterpreter(ready_intent(instruction))).compose(
        tenant_id="tenant-1",
        instruction=instruction,
    )
    clear_proposals_for_tests()
    return record


def test_required_durable_write_failure_never_populates_confirmation_cache() -> None:
    record = _record()
    db = MagicMock()
    with patch(
        "backend.repositories.mission_composition_proposal_repository.MissionCompositionProposalRepository.upsert",
        side_effect=RuntimeError("database unavailable"),
    ):
        persisted = put_proposal(tenant_id="tenant-1", record=record, db=db, require_durable=True)

    assert persisted is False
    assert get_proposal(tenant_id="tenant-1", proposal_id=record.proposal_id) is None
    db.rollback.assert_called_once()


def test_confirmation_reads_the_durable_row_and_validates_the_record() -> None:
    record = _record()
    db = MagicMock()
    row = SimpleNamespace(record_json=record.model_dump(mode="json"))
    with patch(
        "backend.repositories.mission_composition_proposal_repository."
        "MissionCompositionProposalRepository.get_for_update",
        return_value=row,
    ) as locked_get:
        loaded = get_proposal_for_confirmation(
            tenant_id="tenant-1",
            proposal_id=record.proposal_id,
            db=db,
        )

    assert loaded == record
    locked_get.assert_called_once_with(tenant_id="tenant-1", proposal_id=record.proposal_id)


def test_confirmation_store_outage_is_distinct_from_a_missing_proposal() -> None:
    db = MagicMock()
    with patch(
        "backend.repositories.mission_composition_proposal_repository."
        "MissionCompositionProposalRepository.get_for_update",
        side_effect=RuntimeError("database unavailable"),
    ):
        with pytest.raises(ProposalStoreUnavailableError):
            get_proposal_for_confirmation(tenant_id="tenant-1", proposal_id="proposal-1", db=db)
    db.rollback.assert_called_once()


def test_invalid_durable_record_is_not_reported_as_a_missing_proposal() -> None:
    db = MagicMock()
    row = SimpleNamespace(record_json={"unexpected": "shape"})
    with patch(
        "backend.repositories.mission_composition_proposal_repository.MissionCompositionProposalRepository.get_for_update",
        return_value=row,
    ):
        with pytest.raises(ProposalStoreRecordError):
            get_proposal_for_confirmation(tenant_id="tenant-1", proposal_id="proposal-1", db=db)


def test_repository_confirmation_query_uses_row_lock() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None

    MissionCompositionProposalRepository(db).get_for_update(
        tenant_id="tenant-1",
        proposal_id="proposal-1",
    )

    statement = db.execute.call_args.args[0]
    assert statement._for_update_arg is not None


def test_confirmation_is_proposal_idempotent_across_different_retry_keys() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    instruction = "Find roofing companies in Austin."
    interpreter = StaticMissionInterpreter(ready_intent(instruction))
    proposal = MissionCompositionService(interpreter=interpreter).compose(
        tenant_id=tenant_id,
        instruction=instruction,
    )
    interpreter.calls.clear()
    clear_proposals_for_tests()

    db = MagicMock()
    mission_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    plan_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    plan = MissionPlan(
        id=plan_id,
        tenant_id=tenant_id,
        mission_id=mission_id,
        status=MissionPlanStatus.DRAFT.value,
        metadata_json={},
    )
    stored_records = [proposal]

    def _add_mission(mission: Mission) -> Mission:
        mission.id = mission_id
        return mission

    def _persist(**kwargs):  # type: ignore[no-untyped-def]
        stored_records.append(kwargs["record"])
        return True

    with (
        patch("backend.services.mission_composition.service.get_proposal_for_confirmation") as locked_get,
        patch("backend.services.mission_composition.service.put_proposal", side_effect=_persist) as persist,
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_repo_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_repo_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
        patch("backend.services.mission_composition.service.QuotaEnforcementService") as quota_cls,
    ):
        locked_get.side_effect = lambda **_kwargs: stored_records[-1]
        profile_repo_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_repo_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.add.side_effect = _add_mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = plan
        quota_cls.return_value.enforce_mission_budget_gate.return_value = None
        quota_cls.return_value.check_and_record_mission_creation.return_value = None
        service = MissionCompositionService(db=db, interpreter=interpreter)

        first = service.confirm(
            tenant_id=tenant_id,
            proposal_id=proposal.proposal_id,
            interpretation_fingerprint=proposal.interpretation_fingerprint,
            interpretation_confirmed=True,
            idempotency_key="11111111-1111-4111-8111-111111111111",
        )
        second = service.confirm(
            tenant_id=tenant_id,
            proposal_id=proposal.proposal_id,
            interpretation_fingerprint=proposal.interpretation_fingerprint,
            interpretation_confirmed=True,
            idempotency_key="22222222-2222-4222-8222-222222222222",
        )

    assert first["mission_id"] == str(mission_id)
    assert second["mission_id"] == str(mission_id)
    assert mission_repo_cls.return_value.add.call_count == 1
    assert persist.call_count == 1
    assert interpreter.calls == []
    mission = mission_repo_cls.return_value.add.call_args.args[0]
    composition = mission.metadata_json["mission_intake"]["context"]["composition"]
    assert "instruction" not in composition
    assert composition["interpreted_instruction"] == instruction
    assert composition["intent"]["raw_instruction"] == ""
    assert composition["intent"]["interpretation_evidence"] == []
