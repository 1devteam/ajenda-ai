from __future__ import annotations

import uuid

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.contracts import Contradiction
from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_observability import (
    build_deliverable_runtime_state_read,
)
from backend.services.mission_composition.deliverable_runtime_read_model import (
    refresh_deliverable_completion_metadata,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)
from backend.services.mission_composition.epistemic import build_epistemic_context
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.shadow_preview import build_shadow_preview

MISSION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


def _task(*, artifact: str, payload: object, task_id: str) -> ExecutionTask:
    return ExecutionTask(
        id=uuid.UUID(task_id),
        tenant_id="tenant-1",
        mission_id=MISSION_ID,
        title="Deliverable runtime read-model test",
        description="Synthetic completed task for deliverable read-model evaluation.",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "expected_output_contract": {"artifact": artifact},
            "handler_result": {"output": {artifact: payload}},
        },
    )


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


def test_refresh_marks_bound_fields_complete_only_after_required_artifacts_materialize() -> None:
    metadata = _metadata("Return company name, qualification reasons, qualification score, and drafts.")
    qualified = _task(
        artifact="qualified_prospects",
        payload=[
            {
                "company": "Acme",
                "score": 80,
                "reasons": ["fit"],
                "qualification_evidence": {"qualification_dimensions": {"business_fit": 10}},
                "ajenda_relevance": "Ajenda may be relevant to an observed workflow.",
            }
        ],
        task_id="00000000-0000-0000-0000-000000000001",
    )

    partial_metadata, partial = refresh_deliverable_completion_metadata(metadata, [qualified])
    assert partial is not None
    assert partial.complete is False
    partial_state = partial_metadata["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert partial_state["completion"]["complete"] is False
    assert partial_state["lifecycle"]["state"] == "incomplete"

    drafts = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000002",
    )
    complete_metadata, complete = refresh_deliverable_completion_metadata(metadata, [qualified, drafts])
    assert complete is not None
    assert complete.complete is True
    complete_state = complete_metadata["mission_intake"]["context"]["composition"][
        DELIVERABLE_RUNTIME_STATE_METADATA_KEY
    ]
    assert complete_state["completion"]["complete"] is True
    assert complete_state["lifecycle"]["state"] == "current"
    assert complete_state["lifecycle"]["materialized_artifact_count"] == 2
    assert complete_state["grants_execution_authority"] is False


def test_refresh_reconciles_durable_shadow_preview_with_runtime_artifacts() -> None:
    instruction = "Return drafts."
    request = extract_deliverable_request(instruction)
    assert request is not None
    preview = build_shadow_preview(
        proposal_id="proposal-shadow",
        preview_id="preview-shadow",
        task_graph={"schema_version": 1, "nodes": [], "metadata": {}},
        planned_artifact_keys=("introduction_drafts",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    state = build_deliverable_runtime_state(request, shadow_preview=preview)
    assert state is not None
    metadata = {"mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}}
    task = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000099",
    )

    updated, completion = refresh_deliverable_completion_metadata(metadata, [task])

    assert completion is not None and completion.complete is True
    refreshed = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert refreshed["shadow_preview"]["preview_id"] == "preview-shadow"
    assert refreshed["runtime_reconciliation"]["status"] == "aligned"
    assert refreshed["runtime_reconciliation"]["grants_execution_authority"] is False


def test_refresh_preserves_epistemic_reconciliation_metadata() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    state = build_deliverable_runtime_state(request, coverage_assessment=coverage, epistemic_context=epistemic)
    assert state is not None
    metadata = {"mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}}

    updated, completion = refresh_deliverable_completion_metadata(metadata, [])

    assert completion is not None
    lifecycle = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]["lifecycle"]
    assert lifecycle["epistemic_context_schema_version"] == epistemic.schema_version
    assert lifecycle["epistemic_source_classes"] == list(epistemic.source_classes)
    assert lifecycle["epistemic_confidence"] == epistemic.confidence
    assert lifecycle["epistemic_confidence_semantics"] == epistemic.confidence_semantics
    assert lifecycle["epistemic_confidence_basis"] == list(epistemic.confidence_basis)
    assert lifecycle["epistemic_required_evidence"] == list(epistemic.required_evidence)
    assert lifecycle["epistemic_freshness"] == epistemic.freshness
    assert lifecycle["epistemic_contradiction_status"] == epistemic.contradiction_status
    assert lifecycle["epistemic_missing_evidence"] == list(epistemic.missing_evidence)
    assert lifecycle["epistemic_budget_status"] == epistemic.budget_status
    assert lifecycle["epistemic_budget_excesses"] == list(epistemic.budget_excesses)
    assert lifecycle["epistemic_reconciliation"] == "aligned"
    assert lifecycle["coverage_assessment"] == coverage.model_dump(mode="json")


def test_read_projection_rejects_epistemic_source_lineage_drift() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    state = build_deliverable_runtime_state(request, coverage_assessment=coverage, epistemic_context=epistemic)
    assert state is not None
    state["lifecycle"]["epistemic_source_classes"] = ["public_observation"]
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

    import pytest

    with pytest.raises(ValueError, match="epistemic sources"):
        build_deliverable_runtime_state_read(metadata)


def test_refresh_marks_conflicting_duplicate_artifacts_contradictory() -> None:
    metadata = _metadata("Return drafts.")
    first = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000001",
    )
    second = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Different"}],
        task_id="00000000-0000-0000-0000-000000000002",
    )

    updated, completion = refresh_deliverable_completion_metadata(metadata, [first, second])

    assert completion is not None
    state = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert state["lifecycle"]["state"] == "contradictory"
    assert state["lifecycle"]["contradiction_codes"] == ["conflicting_artifact:introduction_drafts"]


def test_refresh_marks_runtime_work_for_blocked_coverage_contradictory() -> None:
    instruction = "Find five dental companies in Austin using local fixture data only and return company name."
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    assert coverage.status == "unsupported_scope"
    state = build_deliverable_runtime_state(
        request,
        coverage_assessment=coverage,
        epistemic_context=build_epistemic_context(intent, coverage),
    )
    assert state is not None
    metadata = {"mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}}
    task = _task(
        artifact="prospect_candidates",
        payload=[{"company": "Impossible Dental", "real": False}],
        task_id="00000000-0000-0000-0000-000000000093",
    )

    updated, _ = refresh_deliverable_completion_metadata(metadata, [task])

    lifecycle = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]["lifecycle"]
    assert lifecycle["state"] == "contradictory"
    assert lifecycle["contradiction_codes"] == ["runtime_work_created_for_blocked_coverage"]


def test_refresh_marks_shadow_reconciliation_contradictory_for_conflicting_artifacts() -> None:
    request = extract_deliverable_request("Return drafts.")
    assert request is not None
    preview = build_shadow_preview(
        proposal_id="proposal-shadow",
        preview_id="preview-shadow",
        task_graph={"nodes": [], "metadata": {}},
        planned_artifact_keys=("introduction_drafts",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    state = build_deliverable_runtime_state(request, shadow_preview=preview)
    assert state is not None
    metadata = {"mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}}
    first = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000091",
    )
    second = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Different"}],
        task_id="00000000-0000-0000-0000-000000000092",
    )

    updated, _ = refresh_deliverable_completion_metadata(metadata, [first, second])

    refreshed = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert refreshed["runtime_reconciliation"]["status"] == "contradictory"
    assert refreshed["runtime_reconciliation"]["contradiction_codes"] == ["conflicting_artifact:introduction_drafts"]


def test_refresh_keeps_bound_field_missing_until_its_artifact_exists() -> None:
    metadata = _metadata("Return website and drafts.")
    drafts = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000001",
    )

    updated, completion = refresh_deliverable_completion_metadata(metadata, [drafts])
    assert completion is not None
    assert completion.complete is False
    statuses = {field.field_key: field.status for field in completion.fields}
    assert statuses["website"] == "missing_artifact"
    assert statuses["drafts"] == "satisfied"
    state = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    assert state["completion"]["complete"] is False


def test_refresh_blocks_exceeded_epistemic_budget_and_read_projection_preserves_it() -> None:
    instruction = "Find five companies in Austin and return company name."
    request = extract_deliverable_request(instruction)
    assert request is not None
    intent = interpret_instruction(instruction).model_copy(
        update={
            "contradictions": [
                Contradiction(
                    field_path="target_entities.location",
                    first_span="in Austin",
                    second_span="not in Austin",
                    first_value="Austin",
                    second_value="not Austin",
                )
            ]
        }
    )
    coverage = assess_coverage(intent)
    epistemic = build_epistemic_context(intent, coverage)
    assert epistemic.budget_status == "exceeded"
    state = build_deliverable_runtime_state(request, epistemic_context=epistemic)
    assert state is not None
    metadata = {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                    "epistemic_context": epistemic.model_dump(mode="json"),
                }
            }
        }
    }

    updated, _ = refresh_deliverable_completion_metadata(metadata, [])
    lifecycle = updated["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]["lifecycle"]
    assert lifecycle["epistemic_reconciliation"] == "blocked"
    assert lifecycle["epistemic_budget_status"] == "exceeded"
    assert lifecycle["epistemic_budget_excesses"] == list(epistemic.budget_excesses)

    read = build_deliverable_runtime_state_read(updated)
    assert read is not None
    assert read.epistemic_reconciliation == "blocked"
    assert read.epistemic_budget_status == "exceeded"
    assert read.epistemic_budget_excesses == epistemic.budget_excesses


def test_refresh_requires_requested_row_count() -> None:
    request = extract_deliverable_request("Return company name and website.")
    assert request is not None
    state = build_deliverable_runtime_state(request, minimum_rows=10)
    assert state is not None
    metadata = {"mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}}
    task = _task(
        artifact="verified_prospect_candidates",
        payload=[
            {
                "company": "One HVAC",
                "real": True,
                "identity_status": "verified",
                "website": "https://example.com",
                "product_description": "HVAC services",
                "research_summary": "HVAC in Dallas",
                "sources": ["https://example.com"],
            }
        ],
        task_id="00000000-0000-0000-0000-000000000003",
    )

    updated, completion = refresh_deliverable_completion_metadata(metadata, [task])

    assert updated
    assert completion is not None
    assert completion.complete is False
    statuses = {field.field_key: field for field in completion.fields}
    assert statuses["website"].status == "insufficient_rows"
    assert statuses["website"].observed_rows == 1
    assert statuses["website"].required_rows == 10


def test_refresh_does_not_mutate_input_metadata() -> None:
    metadata = _metadata("Return drafts.")
    original_state = metadata["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]

    updated, completion = refresh_deliverable_completion_metadata(metadata, [])

    assert completion is not None
    assert updated is not metadata
    assert original_state["completion"] is None


def test_refresh_ignores_invalid_or_absent_runtime_state_fail_closed() -> None:
    invalid = {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: {
                        "schema_version": 1,
                        "grants_execution_authority": True,
                    }
                }
            }
        }
    }

    updated, completion = refresh_deliverable_completion_metadata(invalid, [])
    assert updated == invalid
    assert completion is None

    absent, absent_completion = refresh_deliverable_completion_metadata({"mission_intake": {}}, [])
    assert absent == {"mission_intake": {}}
    assert absent_completion is None
