"""UI request contracts persist reviewable plans without queueing or publishing."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes.mission import _mission_lifecycle_to_read
from backend.api.routes.vertical_ops import VerticalTemplateCreateMissionRequest
from backend.db.tenant_session import activate_tenant_session
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.mission_repository import MissionRepository
from backend.services.vertical_ops.template_service import VerticalOpsTemplateService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("template_id", "step_key", "tool_input", "social"),
    [
        ("vertical.research.v1", "research-internal", {"query": "Research Acme competitors"}, False),
        ("vertical.social.v1", "social-publish", {"platform": "twitter", "content": "Our update"}, True),
    ],
)
def test_ui_plan_inputs_survive_persistence_and_lifecycle_review(
    pg_engine, redis_client, template_id, step_key, tool_input, social
) -> None:
    tenant_id = str(uuid.uuid4())
    operation_key = str(uuid.uuid4())
    payload = {
        "template_id": template_id,
        "mission_objective": "Plan for review",
        "selected_step_keys": [step_key],
        "step_inputs": {step_key: tool_input},
        "queue": False,
    }
    if social:
        payload["idempotency_keys"] = {step_key: operation_key}
        payload["credential_references"] = {
            step_key: {
                "schema_version": 1,
                "credential_id": "social-publisher",
                "provider": "external_social",
                "credential_type": "api_key",
            }
        }
    body = VerticalTemplateCreateMissionRequest.model_validate(payload)
    assert body.queue is False
    with Session(pg_engine) as session:
        session.add(Tenant(id=uuid.UUID(tenant_id), name="UI proof", slug=f"ui-{tenant_id}", plan="free"))
        session.flush()
        activate_tenant_session(session, tenant_id)
        mission = Mission(
            tenant_id=tenant_id,
            objective=body.mission_objective,
            status="planned",
            compliance_category="operational",
            jurisdiction="US-ALL",
            metadata_json={},
        )
        session.add(mission)
        session.flush()
        applied = VerticalOpsTemplateService().apply_to_mission(
            session=session,
            mission=mission,
            template_id=body.template_id,
            selected_step_keys=body.selected_step_keys,
            step_inputs=body.step_inputs,
            idempotency_keys=body.idempotency_keys,
            credential_references=body.credential_references,
        )
        mission_id = mission.id
        assert len(applied.created_task_ids) == 1
        session.commit()

    with Session(pg_engine) as session:
        activate_tenant_session(session, tenant_id)
        mission = MissionRepository(session).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
        assert mission is not None
        lifecycle = _mission_lifecycle_to_read(
            mission=mission, durable_plan=None, evidence_records=[], outcome_reviews=[], retrieval_contracts=[]
        )
        assert lifecycle.task_graph["metadata"]["template_id"] == template_id
        assert lifecycle.task_graph["nodes"][0]["input_contract"]["tool_input"] == tool_input
        task = session.scalars(select(ExecutionTask).where(ExecutionTask.mission_id == mission_id)).one()
        assert task.status == "planned"
        if social:
            assert task.requires_human_review is True
            assert task.metadata_json["tool_invocation"]["idempotency_key"] == operation_key
            assert task.metadata_json["tool_invocation"]["credential_reference"]["credential_id"] == "social-publisher"
        assert MissionRepository(session).get_for_tenant(mission_id=mission_id, tenant_id=str(uuid.uuid4())) is None
    assert redis_client.keys(f"ajenda:queue:{tenant_id}:*") == []
