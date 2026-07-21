"""Unit tests for lease-scoped ability world-state input binding."""

from __future__ import annotations

import uuid

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.tools.mission_input_binding import (
    DependencyNotReadyError,
    apply_input_bindings,
    pending_dependency_keys,
)


def _task(
    *,
    node_key: str,
    status: str,
    mission_id: uuid.UUID,
    tenant_id: str,
    output: dict | None = None,
    dependency_keys: list[str] | None = None,
    tool_input: dict | None = None,
    input_bindings: list[dict] | None = None,
) -> ExecutionTask:
    metadata: dict = {
        "graph_node_key": node_key,
        "dependency_keys": dependency_keys or [],
        "tool_invocation": {
            "schema_version": 1,
            "action": node_key.replace("ability-", "").replace("-", ".", 1) if False else "gtm.email_draft",
            "input": tool_input or {},
        },
        "input_bindings": input_bindings or [],
    }
    if output is not None:
        metadata["handler_result"] = {"output": output}
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        title=node_key,
        description="test",
        status=status,
        metadata_json=metadata,
    )


def test_pending_dependencies_when_upstream_incomplete() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    research = _task(
        node_key="ability-web-research",
        status=ExecutionTaskState.QUEUED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
    )
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.QUEUED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        dependency_keys=["ability-web-research"],
    )
    assert pending_dependency_keys(task=draft, mission_tasks=[research, draft]) == ["ability-web-research"]


def test_bind_prospect_candidates_into_draft_context() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    research = _task(
        node_key="ability-web-research",
        status=ExecutionTaskState.COMPLETED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        output={
            "prospect_candidates": [
                {
                    "prospect_id": "p1",
                    "company": "Fayetteville Roof Pros",
                    "domain": "fayroof.example",
                    "signals": ["top-rated local"],
                    "real": True,
                }
            ]
        },
    )
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.RUNNING.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        dependency_keys=["ability-web-research"],
        tool_input={
            "recipient": "pending.binding@invalid.local",
            "topic": "Introduction",
            "tone": "professional",
            "prospects": [],
            "context": {"binding_required": True, "industry": "roofing"},
        },
        input_bindings=[
            {
                "from_step": "ability-web-research",
                "output_path": "$.prospect_candidates",
                "input_path": "$.input.prospects",
            }
        ],
    )
    bound, audit = apply_input_bindings(
        tool_input=draft.metadata_json["tool_invocation"]["input"],
        task=draft,
        mission_tasks=[research, draft],
    )
    assert bound["prospects"][0]["company"] == "Fayetteville Roof Pros"
    assert bound["context"]["prospect_company"] == "Fayetteville Roof Pros"
    assert "Fayetteville Roof Pros" in bound["topic"]
    assert audit["prospect_count"] == 1
    assert bound["recipient"] == "pending.binding@invalid.local"


def test_bind_fails_closed_when_required_and_empty() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    research = _task(
        node_key="ability-web-research",
        status=ExecutionTaskState.COMPLETED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        output={"prospect_candidates": []},
    )
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.RUNNING.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        dependency_keys=["ability-web-research"],
        tool_input={
            "recipient": "pending.binding@invalid.local",
            "topic": "Introduction",
            "prospects": [],
            "context": {"binding_required": True},
        },
        input_bindings=[
            {
                "from_step": "ability-web-research",
                "output_path": "$.prospect_candidates",
                "input_path": "$.input.prospects",
            }
        ],
    )
    with pytest.raises(Exception) as excinfo:
        apply_input_bindings(
            tool_input=draft.metadata_json["tool_invocation"]["input"],
            task=draft,
            mission_tasks=[research, draft],
        )
    assert "binding_required" in str(excinfo.value).lower() or "no upstream" in str(excinfo.value).lower()


def test_bind_raises_dependency_not_ready() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    research = _task(
        node_key="ability-web-research",
        status=ExecutionTaskState.RUNNING.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
    )
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.RUNNING.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        dependency_keys=["ability-web-research"],
        tool_input={"recipient": "pending.binding@invalid.local", "context": {}},
        input_bindings=[
            {
                "from_step": "ability-web-research",
                "output_path": "$.prospect_candidates",
                "input_path": "$.input.prospects",
            }
        ],
    )
    with pytest.raises(DependencyNotReadyError):
        apply_input_bindings(
            tool_input=draft.metadata_json["tool_invocation"]["input"],
            task=draft,
            mission_tasks=[research, draft],
        )
