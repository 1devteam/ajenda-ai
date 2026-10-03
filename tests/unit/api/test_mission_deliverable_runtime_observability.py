from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.mission import Mission
from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_observability import (
    build_deliverable_runtime_state_read,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)
from backend.services.mission_composition.epistemic import build_epistemic_context
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.semantic_vocabulary import build_semantic_selection


def _metadata(instruction: str) -> dict[str, object]:
    request = extract_deliverable_request(instruction)
    assert request is not None
    state = build_deliverable_runtime_state(request)
    assert state is not None
    return {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                }
            }
        }
    }


def _metadata_with_composition_context(instruction: str) -> dict[str, object]:
    metadata = _metadata(instruction)
    composition = metadata["mission_intake"]["context"]["composition"]  # type: ignore[index]
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    composition["coverage_assessment"] = coverage.model_dump(mode="json")
    composition["epistemic_context"] = build_epistemic_context(intent, coverage).model_dump(mode="json")
    return metadata


def _runtime_state(metadata: dict[str, object]) -> dict[str, object]:
    intake = metadata["mission_intake"]
    assert isinstance(intake, dict)
    context = intake["context"]
    assert isinstance(context, dict)
    composition = context["composition"]
    assert isinstance(composition, dict)
    state = composition[DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert isinstance(state, dict)
    return state


def _mission(*, tenant_id: str, metadata: dict[str, object]) -> Mission:
    now = datetime.now(UTC)
    mission = Mission(
        tenant_id=tenant_id,
        objective="Return a typed RevOps deliverable.",
        status="running",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json=metadata,
    )
    mission.id = uuid.uuid4()
    mission.created_at = now
    mission.updated_at = now
    return mission


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def test_observability_projects_pre_evaluation_state_without_authority() -> None:
    metadata = _metadata("Return company name, website, drafts, and lunar risk index.")

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.requested_fields == ("company_name", "website", "drafts")
    assert read.satisfied_fields == ()
    assert read.missing_fields == ("company_name", "website", "drafts")
    assert read.invalid_fields == ()
    assert read.unproven_fields == ()
    assert read.unresolved_items == ("lunar risk index",)
    assert read.complete is False
    assert read.grants_execution_authority is False


def test_observability_projects_composition_coverage_and_epistemic_context() -> None:
    metadata = _metadata_with_composition_context(
        "Find five software development companies in Austin using local fixture data only and return company name."
    )

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.coverage_assessment is not None
    assert read.coverage_assessment.status == "supported_with_limits"
    assert read.coverage_assessment.grants_execution_authority is False
    assert read.epistemic_context is not None
    assert "local_fixture" in read.epistemic_context.source_classes
    assert read.epistemic_context.grants_execution_authority is False
    assert read.graph_lineage is not None
    assert read.graph_lineage.semantic_owner == "mission_composition.semantic_vocabulary"


def test_observability_rejects_coverage_lineage_drift() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    state = build_deliverable_runtime_state(
        extract_deliverable_request(instruction), coverage_assessment=coverage, epistemic_context=epistemic
    )
    assert state is not None
    composition = {
        "coverage_assessment": coverage.model_dump(mode="json"),
        "epistemic_context": epistemic.model_dump(mode="json"),
        DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
    }
    composition[DELIVERABLE_RUNTIME_STATE_METADATA_KEY]["lifecycle"]["coverage_assessment"]["status"] = (
        "insufficient_capacity"
    )

    with pytest.raises(ValueError, match="coverage does not match"):
        build_deliverable_runtime_state_read({"mission_intake": {"context": {"composition": composition}}})


def test_observability_reconciles_semantic_selection_from_composition() -> None:
    metadata = _metadata_with_composition_context(
        "Research five software development companies in Austin using local fixture data only and return company name."
    )
    composition = metadata["mission_intake"]["context"]["composition"]  # type: ignore[index]
    assert isinstance(composition, dict)
    intent = interpret_instruction(
        "Research five software development companies in Austin using local fixture data only."
    )
    composition["composition_provenance"] = {
        "semantic_selection": build_semantic_selection(
            instruction=intent.raw_instruction,
            requested_outcomes=intent.requested_outcomes,
            selected_job_keys=("research.discover_prospects",),
        ).model_dump(mode="json")
    }

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.semantic_reconciliation == "aligned"
    assert read.semantic_selection is not None
    assert read.semantic_selection.concepts == ("prospect",)
    assert read.grants_execution_authority is False


def test_observability_projects_expired_current_artifact_as_stale() -> None:
    metadata = _metadata("Return company name.")
    state = _runtime_state(metadata)
    state["lifecycle"].update(
        {
            "state": "current",
            "observed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "freshness_window_seconds": 86_400,
        }
    )

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.lifecycle_state == "stale"
    assert read.grants_execution_authority is False


def test_observability_keeps_contradictory_epistemic_artifact_visible() -> None:
    instruction = "Find five software development companies in Austin using public sources and return company name."
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    state = build_deliverable_runtime_state(request, epistemic_context=epistemic)
    assert state is not None
    state["lifecycle"].update(
        {
            "state": "contradictory",
            "contradiction_codes": ["epistemic_unresolved"],
            "epistemic_reconciliation": "blocked",
        }
    )
    metadata = {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                    "coverage_assessment": coverage.model_dump(mode="json"),
                    "epistemic_context": epistemic.model_dump(mode="json"),
                }
            }
        }
    }

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.lifecycle_state == "contradictory"
    assert read.epistemic_reconciliation == "blocked"
    assert read.epistemic_missing_evidence == ("runtime_source_observation",)
    assert read.contradiction_codes == ("epistemic_unresolved",)


def test_observability_rejects_epistemic_lifecycle_drift() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    state = build_deliverable_runtime_state(request, epistemic_context=epistemic)
    assert state is not None
    state["lifecycle"]["epistemic_freshness"] = "current"
    metadata = {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                    "coverage_assessment": coverage.model_dump(mode="json"),
                    "epistemic_context": epistemic.model_dump(mode="json"),
                }
            }
        }
    }

    with pytest.raises(ValueError, match="epistemic freshness"):
        build_deliverable_runtime_state_read(metadata)


def test_observability_projects_validated_partial_completion() -> None:
    metadata = _metadata("Return company name, qualification score, and drafts.")
    state = _runtime_state(metadata)
    state["completion"] = {
        "schema_version": 1,
        "fields": [
            {
                "field_key": "company_name",
                "status": "satisfied",
                "artifact_keys": ["qualified_prospects"],
                "grants_execution_authority": False,
            },
            {
                "field_key": "qualification_score",
                "status": "invalid_artifact",
                "artifact_keys": ["qualified_prospects"],
                "grants_execution_authority": False,
            },
            {
                "field_key": "drafts",
                "status": "missing_artifact",
                "artifact_keys": ["introduction_drafts"],
                "grants_execution_authority": False,
            },
        ],
        "unresolved_request_items": [],
        "grants_execution_authority": False,
        "complete": True,
    }

    read = build_deliverable_runtime_state_read(metadata)

    assert read is not None
    assert read.satisfied_fields == ("company_name",)
    assert read.missing_fields == ("drafts",)
    assert read.invalid_fields == ("qualification_score",)
    assert read.unproven_fields == ()
    assert read.complete is False


def test_observability_returns_none_when_runtime_state_is_absent() -> None:
    assert build_deliverable_runtime_state_read({"mission_intake": {}}) is None


def test_observability_rejects_forged_authority_and_contract_drift() -> None:
    metadata = _metadata("Return company name.")
    state = _runtime_state(metadata)
    state["grants_execution_authority"] = True

    with pytest.raises(ValidationError):
        build_deliverable_runtime_state_read(metadata)

    metadata = _metadata("Return company name and drafts.")
    state = _runtime_state(metadata)
    projection = state["projection"]
    assert isinstance(projection, dict)
    bindings = projection["bindings"]
    assert isinstance(bindings, list)
    projection["bindings"] = bindings[:1]

    with pytest.raises(ValueError, match="projection fields"):
        build_deliverable_runtime_state_read(metadata)


def test_mission_read_exposes_tenant_scoped_deliverable_runtime_state(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    metadata = _metadata("Return company name, website, and drafts.")
    mission = _mission(tenant_id=str(tenant_id), metadata=metadata)
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    monkeypatch.setattr(mission_module, "MissionRepository", lambda _db: repo)
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}")

    assert response.status_code == 200
    state = response.json()["deliverable_runtime_state"]
    assert state == {
        "schema_version": 1,
        "requested_fields": ["company_name", "website", "drafts"],
        "satisfied_fields": [],
        "missing_fields": ["company_name", "website", "drafts"],
        "invalid_fields": [],
        "unproven_fields": [],
        "unresolved_items": [],
        "complete": False,
        "lifecycle_state": "planned",
        "observed_at": None,
        "reconciled_at": None,
        "contradiction_codes": [],
        "epistemic_reconciliation": "not_available",
        "epistemic_missing_evidence": [],
        "epistemic_budget_status": "within_budget",
        "epistemic_budget_excesses": [],
        "coverage_assessment": None,
        "graph_lineage": {
            "schema_version": 1,
            "lineage_version": "1.0.0",
            "semantic_owner": "mission_composition.semantic_vocabulary",
            "semantic_version": "1.0.0",
            "semantic_source_reference": "Ajenda shared semantic vocabulary",
            "epistemic_owner": "mission_composition.epistemic",
            "epistemic_version": "1.0.0",
            "epistemic_source_reference": "Ajenda epistemic context builder",
            "operational_owner": "mission_composition.plan_compiler",
            "operational_version": "1.0.0",
            "operational_source_reference": "Ajenda governed task graph compiler",
            "authority_class": "read_model",
            "grants_execution_authority": False,
        },
        "epistemic_context": None,
        "semantic_selection": None,
        "semantic_reconciliation": "not_available",
        "shadow_preview": None,
        "runtime_reconciliation": None,
        "grants_execution_authority": False,
    }
    repo.get_for_tenant.assert_called_once_with(mission_id=mission.id, tenant_id=str(tenant_id))


def test_mission_read_fails_closed_on_invalid_deliverable_runtime_state(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    metadata = _metadata("Return company name.")
    _runtime_state(metadata)["grants_execution_authority"] = True
    mission = _mission(tenant_id=str(tenant_id), metadata=metadata)
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    monkeypatch.setattr(mission_module, "MissionRepository", lambda _db: repo)
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": "mission deliverable runtime state is invalid"}
