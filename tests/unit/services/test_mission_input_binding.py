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


def test_merge_keeps_enriched_contacts_when_qualify_also_binds() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    qualify = _task(
        node_key="ability-sales-qualify",
        status=ExecutionTaskState.COMPLETED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        output={
            "qualified_prospects": [
                {"prospect_id": "p1", "company": "Acme", "score": 70, "qualified": True}
            ]
        },
    )
    enrich = _task(
        node_key="ability-gtm-lead_enrich",
        status=ExecutionTaskState.COMPLETED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        output={
            "enriched_prospects": [
                {
                    "prospect_id": "p1",
                    "company": "Acme",
                    "domain": "acme.example",
                    "contacts": [{"email": "a@acme.example", "simulated": True}],
                }
            ]
        },
    )
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.RUNNING.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        dependency_keys=["ability-sales-qualify", "ability-gtm-lead_enrich"],
        tool_input={
            "recipient": "pending.binding@invalid.local",
            "topic": "Introduction",
            "prospects": [],
            "context": {"binding_required": True, "industry": "saas"},
        },
        input_bindings=[
            {
                "from_step": "ability-gtm-lead_enrich",
                "output_path": "$.enriched_prospects",
                "input_path": "$.input.prospects",
            },
            {
                "from_step": "ability-sales-qualify",
                "output_path": "$.qualified_prospects",
                "input_path": "$.input.prospects",
            },
        ],
    )
    bound, _audit = apply_input_bindings(
        tool_input=draft.metadata_json["tool_invocation"]["input"],
        task=draft,
        mission_tasks=[qualify, enrich, draft],
    )
    assert len(bound["prospects"]) == 1
    assert bound["prospects"][0]["company"] == "Acme"
    assert bound["prospects"][0]["contacts"][0]["email"] == "a@acme.example"
    assert bound["prospects"][0]["score"] == 70


def _email_send_task(
    *,
    mission_id: uuid.UUID,
    tenant_id: str,
    draft_output: dict,
    binding_required: bool = True,
) -> tuple[ExecutionTask, ExecutionTask]:
    draft = _task(
        node_key="ability-gtm-email_draft",
        status=ExecutionTaskState.COMPLETED.value,
        mission_id=mission_id,
        tenant_id=tenant_id,
        output=draft_output,
    )
    send = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="send",
        description="test",
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={
            "graph_node_key": "ability-gtm-email_send",
            "dependency_keys": ["ability-gtm-email_draft"],
            "tool_invocation": {
                "schema_version": 1,
                "action": "gtm.email_send",
                "input": {
                    "to": "pending.binding@invalid.local",
                    "subject": "Introduction — Ajenda",
                    "body": "Prepared by mission composition; requires bound recipient and human review before send.",
                    "context": {
                        "binding_required": binding_required,
                        "binding_source": "upstream_enriched_prospects",
                    },
                },
            },
            "input_bindings": [
                {
                    "from_step": "ability-gtm-email_draft",
                    "output_path": "$.introduction_drafts",
                    "input_path": "$.input.context.introduction_drafts",
                }
            ],
        },
    )
    return draft, send


def test_email_send_fails_closed_on_placeholder_draft_recipient() -> None:
    from backend.services.tools.mission_input_binding import InputBindingError

    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    draft, send = _email_send_task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        draft_output={
            "introduction_drafts": [
                {
                    "recipient": "pending.binding@invalid.local",
                    "recipient_bound": False,
                    "subject": "Hello Acme",
                    "body": "Personalized draft body for Acme.",
                    "artifact_id": "pitch_email-abc",
                    "company": "Acme",
                }
            ],
        },
    )
    with pytest.raises(InputBindingError, match=r"introduction_drafts|gtm\.email_send|recipient"):
        apply_input_bindings(
            tool_input=send.metadata_json["tool_invocation"]["input"],
            task=send,
            mission_tasks=[draft, send],
        )


@pytest.mark.parametrize(
    "recipient",
    [
        "ops@northwind-logistics.example",
        "ops@test",
        "ops@local",
        "ops@localhost",
        "ops@foo.test",
    ],
)
def test_email_send_rejects_reserved_placeholder_recipients(recipient: str) -> None:
    from backend.services.tools.mission_input_binding import InputBindingError

    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    draft, send = _email_send_task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        draft_output={
            "introduction_drafts": [
                {
                    "recipient": recipient,
                    "recipient_bound": True,
                    "subject": "Hello",
                    "body": "Body",
                    "artifact_id": "pitch_email-ex",
                }
            ],
        },
    )
    with pytest.raises(InputBindingError, match=r"gtm\.email_send|recipient|introduction_drafts"):
        apply_input_bindings(
            tool_input=send.metadata_json["tool_invocation"]["input"],
            task=send,
            mission_tasks=[draft, send],
        )


def test_email_send_binds_when_draft_has_deliverable_recipient() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    draft, send = _email_send_task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        draft_output={
            "introduction_drafts": [
                {
                    "recipient": "ops@acme-roofing.com",
                    "recipient_bound": True,
                    "subject": "Hello Acme",
                    "body": "Personalized draft body for Acme.",
                    "artifact_id": "pitch_email-abc",
                    "company": "Acme",
                }
            ],
        },
    )
    bound, audit = apply_input_bindings(
        tool_input=send.metadata_json["tool_invocation"]["input"],
        task=send,
        mission_tasks=[draft, send],
    )
    assert bound["to"] == "ops@acme-roofing.com"
    assert bound["subject"] == "Hello Acme"
    assert "Personalized draft body" in bound["body"]
    assert bound["artifact_id"] == "pitch_email-abc"
    assert bound["context"]["recipient_bound"] is True
    assert audit["action"] == "gtm.email_send"


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
