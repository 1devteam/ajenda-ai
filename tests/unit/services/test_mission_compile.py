"""Unit tests for server mission compile (ajenda-mission-compiler)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.enums import MissionPlanStatus, MissionState
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    MissionPlan,
)
from backend.services.mission_composition.service import (
    COMPILER_NAME,
    COMPILER_VERSION,
    MissionCompositionError,
    MissionCompositionService,
)


def _mission(
    *, objective: str = "Find three roofing companies in Austin and draft outreach without sending."
) -> Mission:
    mid = uuid.uuid4()
    return Mission(
        id=mid,
        tenant_id="11111111-1111-1111-1111-111111111111",
        objective=objective,
        status=MissionState.PLANNED.value,
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={
            MISSION_INTAKE_METADATA_KEY: {
                "schema_version": 1,
                "allowed_actions": [
                    "google_calendar.events_read",
                    "linkedin.profile_read",
                    "gtm.email_send",
                ],
                "success_criteria": [],
                "constraints": [],
                "context": {},
            }
        },
    )


def test_compile_for_mission_uses_server_composition_not_kitchen_sink() -> None:
    mission = _mission()
    tenant_id = mission.tenant_id
    service = MissionCompositionService(db=MagicMock())

    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )

        result = service.compile_for_mission(
            tenant_id=tenant_id,
            mission_id=mission.id,
            persist=True,
            actor_id="operator-1",
            source="mission_dispatch_ui",
        )

    assert result["compiler"]["name"] == COMPILER_NAME
    assert result["compiler"]["version"] == COMPILER_VERSION
    assert result["mission_id"] == str(mission.id)
    assert result["grants_execution_authority"] is False
    assert result["runtime_queued"] is False
    # Kitchen-sink calendar/linkedin should not be forced by stale intake.
    assert "google_calendar.events_read" not in result["display"]["allowed_actions"]
    assert "linkedin.profile_read" not in result["display"]["allowed_actions"]
    # No-send constraint should keep send off the ready path.
    assert "gtm.email_send" not in result["display"]["allowed_actions"]
    assert result["compile_status"] in {"ready", "blocked", "needs_clarification"}
    assert result["validation"]["validator"] == "server"
    assert result["validation"]["validation_status"] in {"valid", "invalid", "warning"}
    graph = result["task_graph"]
    assert isinstance(graph.get("nodes"), list)
    # No client-forged SE approver on nodes.
    for node in graph["nodes"]:
        if not isinstance(node, dict):
            continue
        contract = node.get("input_contract") or {}
        constraints = contract.get("execution_constraints") or {}
        auth = constraints.get("side_effect_authorization") if isinstance(constraints, dict) else None
        if isinstance(auth, dict):
            assert auth.get("approved_by") != "mission-dispatch-ui"
            assert (
                "mission-dispatch" not in str(auth.get("approved_by") or "").lower()
                or auth.get("approved_by") == "operator-1"
            )


def test_compile_persists_graph_and_refreshes_allowed_actions() -> None:
    mission = _mission()
    tenant_id = mission.tenant_id
    service = MissionCompositionService(db=MagicMock())

    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )

        result = service.compile_for_mission(
            tenant_id=tenant_id,
            mission_id=mission.id,
            persist=True,
            actor_id="operator-1",
        )

        assert result["compile_status"] == "ready"
        assert result["persisted"] is True
        mission_repo_cls.return_value.update_metadata.assert_called()
        _kwargs = mission_repo_cls.return_value.update_metadata.call_args.kwargs
        updated = _kwargs["metadata_json"]
        assert MISSION_TASK_GRAPH_METADATA_KEY in updated
        intake = updated[MISSION_INTAKE_METADATA_KEY]
        assert intake["allowed_actions"] == result["display"]["allowed_actions"]
        assert "google_calendar.events_read" not in intake["allowed_actions"]
        graph_meta = updated[MISSION_TASK_GRAPH_METADATA_KEY]
        assert (graph_meta.get("metadata") or {}).get("generated_by") == "ajenda-mission-compiler"
        assert "graph_fingerprint" in graph_meta
        from backend.domain.mission import MISSION_GRAPH_MATERIALIZATION_METADATA_KEY

        mat = updated.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
        assert isinstance(mat, dict)
        assert mat.get("materialization_source") == "ajenda-mission-compiler"
        assert mat.get("materialization_status") == "validated"
        assert (mat.get("graph_validation_result") or {}).get("validation_status") == "valid"
        assert (mat.get("graph_validation_result") or {}).get("summary", "").startswith("Server compile")


def test_compile_supersedes_runtime_task_materialization_and_cancels_planned_tasks() -> None:
    """Recompile must not leave old planned ExecutionTasks queueable (Codex P1)."""
    planned_task_id = uuid.uuid4()
    mission = _mission()
    mission.metadata_json[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = {
        "admission_status": "admitted",
        "admitted_at": "2026-01-01T00:00:00+00:00",
    }
    mission.metadata_json[MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY] = {
        "materialization_status": "materialized",
        "created_execution_task_ids": [str(planned_task_id)],
        "task_count": 1,
        "materialized_at": "2026-01-01T00:00:00+00:00",
    }
    mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY] = {
        "schema_version": 1,
        "graph_version": 1,
        "graph_fingerprint": "sha256:old",
        "nodes": [],
        "edges": [],
        "metadata": {},
    }
    tenant_id = mission.tenant_id
    service = MissionCompositionService(db=MagicMock())
    cancelled_task = MagicMock()
    cancelled_task.id = planned_task_id

    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
        patch("backend.services.mission_composition.service.ExecutionTaskRepository") as task_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )
        task_repo_cls.return_value.cancel_planned_by_ids_for_mission.return_value = [cancelled_task]

        result = service.compile_for_mission(
            tenant_id=tenant_id,
            mission_id=mission.id,
            persist=True,
            actor_id="operator-1",
        )

        assert result["compile_status"] == "ready"
        assert result["persisted"] is True
        task_repo_cls.return_value.cancel_planned_by_ids_for_mission.assert_called_once_with(
            tenant_id=tenant_id,
            mission_id=mission.id,
            task_ids=[planned_task_id],
        )
        updated = mission_repo_cls.return_value.update_metadata.call_args.kwargs["metadata_json"]
        admission = updated[MISSION_RUNTIME_ADMISSION_METADATA_KEY]
        assert admission["admission_status"] == "superseded"
        assert admission["superseded_reason"] == "mission_recompiled"
        rtm = updated[MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY]
        assert rtm["materialization_status"] == "superseded"
        assert rtm["superseded_reason"] == "mission_recompiled"
        assert rtm["cancelled_execution_task_ids"] == [str(planned_task_id)]
        assert rtm["superseded_by_graph_version"] == updated[MISSION_TASK_GRAPH_METADATA_KEY]["graph_version"]
        assert rtm["superseded_by_graph_fingerprint"] == updated[MISSION_TASK_GRAPH_METADATA_KEY]["graph_fingerprint"]
        mat = updated[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY]
        assert mat["materialization_status"] == "validated"
        assert mat["materialization_source"] == COMPILER_NAME


def test_compile_mission_not_found() -> None:
    service = MissionCompositionService(db=MagicMock())
    with patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls:
        mission_repo_cls.return_value.get_for_tenant.return_value = None
        with pytest.raises(MissionCompositionError) as exc:
            service.compile_for_mission(
                tenant_id="11111111-1111-1111-1111-111111111111",
                mission_id=uuid.uuid4(),
            )
    assert exc.value.code == "MISSION_NOT_FOUND"


def test_compile_uses_stored_composition_when_client_omits_instruction() -> None:
    """Dispatch UI omits instruction; server uses stored composition over lossy objective."""
    original = (
        "Research five competitors of Acme Roofing in Northwest Arkansas, "
        "score them, and prepare outreach drafts for the top three."
    )
    mangled = "Identify and prepare outreach for qualified the requested market prospects without sending messages."
    mission = _mission(objective=mangled)
    mission.metadata_json[MISSION_INTAKE_METADATA_KEY]["context"] = {
        "composition": {
            "proposal_id": "ff1a8b6f-c8d2-4c2f-9db0-2b9b3864443e",
            "instruction": original,
        }
    }
    tenant_id = mission.tenant_id
    service = MissionCompositionService(db=MagicMock())

    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )

        result = service.compile_for_mission(
            tenant_id=tenant_id,
            mission_id=mission.id,
            instruction=None,
            persist=False,
            actor_id="operator-1",
            source="mission_dispatch_ui",
        )

    assert result["compile_status"] == "ready"
    assert "web.research" in result["display"]["allowed_actions"]
    assert "sales.qualify" in result["display"]["allowed_actions"]
    assert "gtm.email_draft" in result["display"]["allowed_actions"]
    assert "gtm.email_send" not in result["display"]["allowed_actions"]


def test_compile_honors_explicit_client_instruction_over_stored() -> None:
    """API recompile with a new instruction must not be silently discarded."""
    stored = "Research five roofing companies in Austin and prepare drafts without sending."
    revised = (
        "Research five competitors of Acme Roofing in Northwest Arkansas, "
        "score them, and prepare outreach drafts for the top three."
    )
    mission = _mission(objective=stored)
    mission.metadata_json[MISSION_INTAKE_METADATA_KEY]["context"] = {
        "composition": {
            "proposal_id": "ff1a8b6f-c8d2-4c2f-9db0-2b9b3864443e",
            "instruction": stored,
        }
    }
    service = MissionCompositionService(db=MagicMock())
    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )
        result = service.compile_for_mission(
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            instruction=revised,
            persist=False,
            actor_id="operator-1",
        )
    assert result["compile_status"] == "ready"
    assert "web.research" in result["display"]["allowed_actions"]
    # Revised instruction uses competitor scoring path (qualify).
    assert "sales.qualify" in result["display"]["allowed_actions"]


def test_compile_binding_manifest_present_when_steps_have_deps() -> None:
    mission = _mission(
        objective="Research roofing companies in Fayetteville AR and prepare introduction drafts without sending."
    )
    service = MissionCompositionService(db=MagicMock())
    with (
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
    ):
        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        mission_repo_cls.return_value.get_for_tenant.return_value = mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=uuid.uuid4(),
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )
        result = service.compile_for_mission(
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            persist=False,
            actor_id="operator-1",
        )
    assert isinstance(result["binding_manifest"], list)
    assert isinstance(result["display"]["steps"], list)
    assert result["compiler"]["name"] == "ajenda-mission-compiler"
