"""Prove a governed source read can become an approved write, not a hidden read side effect."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_understanding import BusinessMeasurement
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from tests.integration.credentials._invoke_authority_helpers import (
    seed_capability_adapter_authority,
    side_effect_authorization,
)
from tests.integration.intelligence.canonical_decision_runtime import execute_canonical_action
from tests.integration.intelligence.test_source_verified_measurement_real import _snapshot
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration

ACTION = "business.ingest_runtime_measurement"


def test_governed_runtime_measurement_ingress_holds_without_approval_and_commits_with_it(
    pg_engine, queue_adapter
) -> None:
    tenant = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    record_id = "governed-measurement-source"
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Governed source", slug=f"governed-{tenant[:8]}", plan="free"))
        setup.add(Mission(id=mission_id, tenant_id=tenant, objective="Governed source handoff"))
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=record_id,
            data={"name": "Tenant-owned KPI source", "operating_measurement": _snapshot(subject_id=record_id)},
        )
        persist_test_operating_charter(setup, tenant_id=tenant, allow_perform=(ACTION,))
        setup.commit()

    source_evidence = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="governed-source-observer",
    )
    with factory() as authority:
        references = seed_capability_adapter_authority(
            authority,
            tenant_id=tenant,
            action_name=ACTION,
            side_effect_classification="internal_write",
        )
        authority.commit()

    # The action is a real write: merely supplying capability and adapter
    # promotion must not turn a planned task into executable permission.
    blocked_task_id = uuid.uuid4()
    invocation = {"schema_version": 1, "action": ACTION, "input": {"source_evidence_id": str(source_evidence.id)}}
    with factory() as blocked:
        blocked.add(
            ExecutionTask(
                id=blocked_task_id,
                tenant_id=tenant,
                mission_id=mission_id,
                title="Unapproved measurement handoff",
                description="The runtime must keep this task in human review",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={"task_type": "tool.invoke", "tool_invocation": invocation, **references},
            )
        )
        blocked.flush()
        result = ExecutionCoordinator(blocked, queue_adapter).queue_task(tenant_id=tenant, task_id=blocked_task_id)
        assert result.ok is False
        assert "independent human approval" in result.reason
        blocked.commit()

    with factory() as inspect:
        activate_tenant_session(inspect, tenant)
        assert inspect.scalars(select(BusinessMeasurement).where(BusinessMeasurement.tenant_id == tenant)).all() == []

    approved = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action=ACTION,
        action_input={"source_evidence_id": str(source_evidence.id)},
        worker_label="approved-measurement-admission",
        runtime_authority_metadata={
            **references,
            **side_effect_authorization(allowed_actions=[ACTION]),
        },
    )
    assert approved.evidence_source == "business_measurement_ingress"
    output = approved.structured_payload
    assert output["source_evidence_id"] == str(source_evidence.id)
    assert output["source_kind"] == "source_verified"
    assert output["need_id"] is not None
    assert output["source_independence_established"] is False
    assert output["kpi_truth_independently_verified"] is False

    replay = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action=ACTION,
        action_input={"source_evidence_id": str(source_evidence.id)},
        worker_label="approved-measurement-replay",
        runtime_authority_metadata={
            **references,
            **side_effect_authorization(allowed_actions=[ACTION]),
        },
    )
    assert replay.structured_payload["measurement_id"] == output["measurement_id"]
    with factory() as inspect:
        activate_tenant_session(inspect, tenant)
        rows = inspect.scalars(select(BusinessMeasurement).where(BusinessMeasurement.tenant_id == tenant)).all()
        assert len(rows) == 1
        assert str(rows[0].id) == output["measurement_id"]
