from __future__ import annotations

import uuid

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_read_model import (
    refresh_deliverable_completion_metadata,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)

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
    assert complete_state["grants_execution_authority"] is False


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
