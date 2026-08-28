from __future__ import annotations

import uuid

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_runtime_artifacts import (
    collect_materialized_artifacts,
    declared_artifact_key,
    materialized_artifact_for_task,
)


def _task(*, artifact: str, payload: object, task_id: str = "00000000-0000-0000-0000-000000000001") -> ExecutionTask:
    return ExecutionTask(
        id=uuid.UUID(task_id),
        tenant_id="tenant-1",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "expected_output_contract": {"artifact": artifact},
            "handler_result": {"output": {artifact: payload}},
        },
    )


def test_declared_artifact_key_reads_server_output_contract() -> None:
    task = _task(artifact="qualified_prospects", payload=[])
    assert declared_artifact_key(task) == "qualified_prospects"


def test_materialized_artifact_requires_completed_task_and_matching_output_key() -> None:
    task = _task(artifact="qualified_prospects", payload=[{"company": "Acme", "score": 80, "reasons": ["fit"]}])
    artifact = materialized_artifact_for_task(task)
    assert artifact is not None
    assert artifact.artifact_key == "qualified_prospects"
    assert artifact.payload == [{"company": "Acme", "score": 80, "reasons": ["fit"]}]

    task.status = ExecutionTaskState.RUNNING.value
    assert materialized_artifact_for_task(task) is None


def test_materialized_artifact_fails_closed_when_handler_output_does_not_name_declared_artifact() -> None:
    task = _task(artifact="qualified_prospects", payload=[])
    task.metadata_json = {
        **task.metadata_json,
        "handler_result": {"output": {"score": 80}},
    }
    assert materialized_artifact_for_task(task) is None


def test_collect_materialized_artifacts_accumulates_distinct_sibling_outputs() -> None:
    qualified = _task(
        artifact="qualified_prospects",
        payload=[{"company": "Acme", "score": 80, "reasons": ["fit"]}],
    )
    drafts = _task(
        artifact="introduction_drafts",
        payload=[{"company": "Acme", "subject": "Hello"}],
        task_id="00000000-0000-0000-0000-000000000002",
    )

    artifacts = collect_materialized_artifacts([drafts, qualified])
    assert [artifact.artifact_key for artifact in artifacts] == ["introduction_drafts", "qualified_prospects"]


def test_collect_materialized_artifacts_collapses_identical_retry_payloads() -> None:
    first = _task(artifact="qualified_prospects", payload=[{"company": "Acme"}])
    retry = _task(
        artifact="qualified_prospects",
        payload=[{"company": "Acme"}],
        task_id="00000000-0000-0000-0000-000000000002",
    )

    artifacts = collect_materialized_artifacts([retry, first])
    assert len(artifacts) == 1
    assert artifacts[0].artifact_key == "qualified_prospects"


def test_collect_materialized_artifacts_omits_conflicting_duplicate_payloads() -> None:
    first = _task(artifact="qualified_prospects", payload=[{"company": "Acme"}])
    conflicting = _task(
        artifact="qualified_prospects",
        payload=[{"company": "Other"}],
        task_id="00000000-0000-0000-0000-000000000002",
    )

    assert collect_materialized_artifacts([first, conflicting]) == ()
