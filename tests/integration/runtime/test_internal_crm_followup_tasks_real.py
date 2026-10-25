"""Real runtime proof for composed internal CRM follow-up task persistence."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.light_crm.records import LightCrmRecordService
from tests.integration.credentials._invoke_authority_helpers import (
    seed_capability_adapter_authority,
    side_effect_authorization,
)
from tests.integration.intelligence.canonical_decision_runtime import execute_canonical_action
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def test_worker_persists_and_reads_back_composed_followup_tasks_for_existing_contacts(pg_engine, queue_adapter) -> None:
    """The runtime may write tasks only for tenant-owned bound contact records."""

    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    contact_ids = [f"contact-followup-{index}" for index in range(1, 4)]
    with session_factory() as setup:
        setup.add(
            Tenant(id=uuid.UUID(tenant_id), name="Follow-up Tenant", slug=f"followup-{tenant_id[:8]}", plan="free")
        )
        setup.add(Mission(id=mission_id, tenant_id=tenant_id, objective="Create internal CRM follow-up tasks"))
        setup.flush()
        activate_tenant_session(setup, tenant_id)
        persist_test_operating_charter(setup, tenant_id=tenant_id)
        records = TenantInternalRecordRepository(setup)
        for index, contact_id in enumerate(contact_ids, start=1):
            records.write_record(
                tenant_id=tenant_id,
                record_type="contact",
                record_id=contact_id,
                data={"id": contact_id, "email": f"prospect-{index}@example.test", "name": f"Prospect {index}"},
            )
        authority = seed_capability_adapter_authority(
            setup,
            tenant_id=tenant_id,
            action_name="sales.create_followup_task",
            side_effect_classification="non_idempotent_write",
        )
        setup.commit()

    evidence = execute_canonical_action(
        factory=session_factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="sales.create_followup_task",
        action_input={
            "record_type": "task",
            "data": {"title": "Follow up with existing prospect", "priority": "high", "status": "open"},
            "context": {
                "source": "mission_composition",
                "crm_records": [{"id": contact_id} for contact_id in contact_ids],
                "requested_quantity": 3,
                "due_policy": "three_days_after_execution",
            },
        },
        worker_label="internal-crm-followup",
        runtime_authority_metadata={
            **authority,
            **side_effect_authorization(allowed_actions=["sales.create_followup_task"]),
        },
    )

    output = evidence.structured_payload
    follow_up_tasks = output["follow_up_tasks"]
    assert len(follow_up_tasks) == 3
    assert {item["prospect_id"] for item in follow_up_tasks} == set(contact_ids)
    assert all(item["status"] == "open" and item["priority"] == "high" for item in follow_up_tasks)
    assert all(item["readback_verified"] is True for item in follow_up_tasks)

    with session_factory() as verify:
        activate_tenant_session(verify, tenant_id)
        crm = LightCrmRecordService(session=verify)
        persisted = crm.list_records(tenant_id=tenant_id, record_type="task", limit=10)
        assert {item["id"] for item in persisted} == {item["id"] for item in follow_up_tasks}
        for task in persisted:
            assert task["related_type"] == "contact"
            assert task["related_id"] in contact_ids
            links = crm.list_relationships_for_record(
                tenant_id=tenant_id,
                record_type="task",
                record_id=str(task["id"]),
            )
            assert len(links) == 1
            assert links[0]["relationship_type"] == "follows_up_with"
            assert links[0]["to_id"] == task["related_id"]
        assert (
            verify.scalar(select(Mission.id).where(Mission.id == mission_id, Mission.tenant_id == tenant_id))
            == mission_id
        )
