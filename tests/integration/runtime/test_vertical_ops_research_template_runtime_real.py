"""Integration proof: vertical research template → queue → lease → tool.invoke → evidence.

ADR-0007 Phase B runtime proof for template ``vertical.research.v1`` (default step
``web.research``). Uses the existing ExecutionCoordinator + WorkerRuntimeService +
TaskDispatcher spine. No parallel agent swarm runtime.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.demo_tenant_bootstrap import DemoTenantBootstrapService
from backend.services.internet.contracts import SearchBundle, SearchHit
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.vertical_ops.template_service import (
    VERTICAL_TEMPLATE_METADATA_KEY,
    VerticalOpsTemplateService,
)
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration


def test_vertical_research_template_queues_claims_executes_and_persists_evidence(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-vertical-ops-research"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Vertical Ops Tenant",
                slug=f"vertical-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(
            tenant_id=tenant_id,
            objective="Vertical research proof mission",
            status="planned",
            metadata_json={"schema_version": 1, "source": "vertical-ops-integration"},
            compliance_category="operational",
            jurisdiction="US-ALL",
        )
        setup_session.add(mission)
        setup_session.flush()

        quota = QuotaEnforcementService(setup_session)
        quota.check_and_record_mission_creation(uuid.UUID(tenant_id))
        # Pre-seed durable records so web.research does not seed inside the
        # dispatcher-held session (avoids long lock waits under concurrent heartbeat).
        activate_tenant_session(setup_session, tenant_id)
        DemoTenantBootstrapService(setup_session).ensure_seeded_if_empty(tenant_id=tenant_id)
        setup_session.flush()

        service = VerticalOpsTemplateService()
        applied, queued = service.apply_and_queue(
            session=setup_session,
            queue=queue_adapter,
            mission=mission,
            template_id="vertical.research.v1",
            step_inputs={
                "research-internal": {
                    "query": "Acme competitors",
                    "company": "Acme",
                }
            },
            approved_by="vertical-ops-integration",
            approval_reason="Phase B research template runtime proof.",
            create_runtime_authority=False,
        )
        quota.check_and_record_task_creation(uuid.UUID(tenant_id), count=len(applied.created_task_ids))
        assert len(applied.created_task_ids) == 1
        assert queued.queued_task_ids == applied.created_task_ids
        assert queued.blocked_task_ids == ()
        task_id = applied.created_task_ids[0]

        template_meta = mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]
        assert template_meta["template_id"] == "vertical.research.v1"
        assert template_meta["grants_execution_authority"] is False
        assert template_meta["created_task_ids"] == [str(task_id)]

        planned_task = setup_session.get(ExecutionTask, task_id)
        assert planned_task is not None
        assert planned_task.metadata_json["task_type"] == "tool.invoke"
        assert planned_task.metadata_json["tool_invocation"]["action"] == "web.research"
        assert planned_task.metadata_json["vertical_role_key"] == "vertical.research"
        assert planned_task.metadata_json["template_id"] == "vertical.research.v1"
        assert planned_task.status == ExecutionTaskState.QUEUED.value
        setup_session.commit()

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        final_lease = verify_session.get(WorkerLease, lease_id)
        lineage = verify_session.scalars(
            select(LineageRecord).where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        ).all()
        evidence_records = verify_session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.execution_task_id == task_id,
                EvidenceRecord.evidence_source == "tool.invoke.web.research",
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        payload = lineage[0].metadata_json
        assert lineage[0].relationship_reason == "tool action completed"
        assert payload["handler"] == "tool.invoke"
        assert payload["action"] == "web.research"
        assert payload["output"]["query"] == "Acme competitors"
        assert payload["output"]["source"] == "ajenda_brain"
        assert payload["evidence"][0]["action_name"] == "web.research"
        assert payload["evidence"][0]["tenant_id"] == tenant_id
        assert len(evidence_records) == 1
        evidence = evidence_records[0]
        assert evidence.mission_id == final_task.mission_id
        assert evidence.evidence_type == "execution_trace"
        assert evidence.provenance_metadata["tool_evidence_type"] == "action_result"
        assert evidence.structured_payload["query"] == "Acme competitors"
        assert redis_client.hlen(f"ajenda:queue:{tenant_id}:v2:processing-payloads") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()


def test_vertical_public_research_resolves_external_authority_and_persists_runtime_evidence(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist complete governed-search fallback provenance through runtime.

    The action traverses apply → authority records → queue → lease → dispatcher
    → evidence persistence.  The provider implementations are controlled, but
    ``public_search`` itself performs the provider-chain fallback.  This is a
    PostgreSQL/Redis persistence proof, not a claim that either provider was
    contacted over the network.
    """

    tenant_id = str(uuid.uuid4())
    worker_id = "worker-vertical-ops-public-research"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    class _FailingProvider:
        name = "controlled_primary"

        def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
            assert "Dallas" in query
            assert limit >= 1
            assert timeout_seconds > 0
            return SearchBundle(
                provider=self.name,
                real=False,
                status_code=429,
                error="controlled rate limit",
            )

    class _FallbackProvider:
        name = "controlled_fallback"

        def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
            assert "Dallas" in query
            assert limit >= 1
            assert timeout_seconds > 0
            return SearchBundle(
                provider=self.name,
                real=True,
                status_code=200,
                results=(
                    SearchHit(
                        title="Example Heating & Air",
                        snippet="Dallas HVAC company",
                        url="https://example.com/hvac",
                        source="controlled_public_result",
                    ),
                ),
            )

    monkeypatch.setattr(
        "backend.services.internet.search.resolve_public_search_provider_chain",
        lambda **_kwargs: [_FailingProvider(), _FallbackProvider()],
    )
    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Vertical public research",
                slug=f"vertical-public-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(
            tenant_id=tenant_id,
            objective="Public HVAC research proof mission",
            status="planned",
            metadata_json={"schema_version": 1, "source": "vertical-ops-integration"},
            compliance_category="operational",
            jurisdiction="US-ALL",
        )
        setup_session.add(mission)
        setup_session.flush()
        activate_tenant_session(setup_session, tenant_id)

        applied, queued = VerticalOpsTemplateService().apply_and_queue(
            session=setup_session,
            queue=queue_adapter,
            mission=mission,
            template_id="vertical.research.v1",
            step_inputs={
                "research-internal": {
                    "query": "HVAC companies in Dallas Texas",
                    "include_public_search": True,
                    "exclude_internal_records": True,
                }
            },
            approved_by="vertical-ops-integration",
            approval_reason="Public-read authority runtime proof.",
        )
        assert queued.queued_task_ids == applied.created_task_ids
        task_id = applied.created_task_ids[0]
        planned_task = setup_session.get(ExecutionTask, task_id)
        assert planned_task is not None
        assert planned_task.metadata_json["side_effect_class"] == "external_read"
        assert planned_task.metadata_json["capability_reference"]
        assert planned_task.metadata_json["adapter_reference"]
        setup_session.commit()

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        activate_tenant_session(verify_session, tenant_id)
        task = verify_session.get(ExecutionTask, task_id)
        lease = verify_session.get(WorkerLease, lease_id)
        evidence = verify_session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.execution_task_id == task_id,
            )
        ).all()
        assert task is not None
        assert task.status == ExecutionTaskState.COMPLETED.value
        assert task.metadata_json["handler_result"]["side_effect_class"] == "external_read"
        output = task.metadata_json["handler_result"]["output"]
        assert output["provider_attempts"]
        attempts = output["provider_attempts"]
        assert len(attempts) == 4  # primary/fallback for each deterministic query variant
        assert [attempt["provider"] for attempt in attempts] == [
            "controlled_primary",
            "controlled_fallback",
            "controlled_primary",
            "controlled_fallback",
        ]
        assert [attempt["outcome"] for attempt in attempts] == ["failure", "results", "failure", "results"]
        assert [attempt["status_code"] for attempt in attempts] == [429, 200, 429, 200]
        assert [attempt["error"] for attempt in attempts] == [
            "controlled rate limit",
            None,
            "controlled rate limit",
            None,
        ]
        assert output["search_providers"] == ["controlled_fallback"]
        assert output["web_results"]
        assert all(item["source"] == "controlled_public_result" for item in output["web_results"])
        assert lease is not None and lease.status == WorkerLeaseState.RELEASED.value
        assert len(evidence) == 1
        assert redis_client.hlen(f"ajenda:queue:{tenant_id}:v2:processing-payloads") == 0
    finally:
        verify_session.close()


def test_vertical_template_dependencies_defer_until_the_prerequisite_completes(pg_engine, queue_adapter) -> None:
    """The direct template path emits the dependency key consumed by the worker."""

    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Vertical dependency research",
                slug=f"vertical-dependency-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(
            tenant_id=tenant_id,
            objective="Vertical dependency proof mission",
            status="planned",
            metadata_json={"schema_version": 1, "source": "vertical-ops-integration"},
            compliance_category="operational",
            jurisdiction="US-ALL",
        )
        setup_session.add(mission)
        setup_session.flush()
        activate_tenant_session(setup_session, tenant_id)

        service = VerticalOpsTemplateService()
        applied = service.apply_to_mission(
            session=setup_session,
            mission=mission,
            template_id="vertical.research.v1",
            selected_step_keys=("research-internal", "research-sales"),
            step_inputs={
                "research-internal": {"query": "Acme competitors"},
                "research-sales": {"lead": {"company": "Acme"}},
            },
            create_runtime_authority=False,
        )
        tasks = {
            task.metadata_json["template_step_key"]: task
            for task in (setup_session.get(ExecutionTask, task_id) for task_id in applied.created_task_ids)
            if task is not None
        }
        research = tasks["research-internal"]
        sales = tasks["research-sales"]
        assert sales.metadata_json["dependency_keys"] == ["research-internal"]

        service.queue_planned_tasks(
            session=setup_session,
            queue=queue_adapter,
            tenant_id=tenant_id,
            task_ids=(sales.id,),
            template_id="vertical.research.v1",
        )
        setup_session.commit()

        deferred = WorkerRuntimeService(setup_session, queue_adapter).claim_next_task(
            tenant_id=tenant_id,
            worker_id="worker-vertical-dependency-deferred",
        )
        assert deferred is None
        setup_session.expire(sales)
        assert sales.status == ExecutionTaskState.QUEUED.value
        assert sales.metadata_json["dependency_deferral"]["pending_keys"] == ["research-internal"]

        service.queue_planned_tasks(
            session=setup_session,
            queue=queue_adapter,
            tenant_id=tenant_id,
            task_ids=(research.id,),
            template_id="vertical.research.v1",
        )
        setup_session.commit()

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed_research = None
        # The deferred child was re-admitted before its parent.  The canonical
        # queue is FIFO, so it may be encountered and deferred once more
        # before the newly queued parent is claimable.
        for _ in range(3):
            claimed = runtime.claim_next_task(
                tenant_id=tenant_id,
                worker_id="worker-vertical-dependency-research",
            )
            if claimed is not None:
                claimed_research = claimed
                break
        assert claimed_research is not None and claimed_research.id == research.id
        research_lease_id = uuid.UUID(str(claimed_research.metadata_json["worker_lease_id"]))
        runtime.heartbeat(
            tenant_id=tenant_id,
            lease_id=research_lease_id,
            worker_id="worker-vertical-dependency-research",
        )
        runtime.start_execution(
            tenant_id=tenant_id,
            lease_id=research_lease_id,
            worker_id="worker-vertical-dependency-research",
        )
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id="worker-vertical-dependency-research",
        tenant_id=tenant_id,
    ).execute(task_id=research.id, lease_id=research_lease_id)

    finish_session = session_factory()
    try:
        activate_tenant_session(finish_session, tenant_id)
        runtime = WorkerRuntimeService(finish_session, queue_adapter)
        claimed_sales = runtime.claim_next_task(
            tenant_id=tenant_id,
            worker_id="worker-vertical-dependency-sales",
        )
        assert claimed_sales is not None and claimed_sales.id == sales.id
        sales_lease_id = uuid.UUID(str(claimed_sales.metadata_json["worker_lease_id"]))
        runtime.heartbeat(
            tenant_id=tenant_id,
            lease_id=sales_lease_id,
            worker_id="worker-vertical-dependency-sales",
        )
        runtime.start_execution(
            tenant_id=tenant_id,
            lease_id=sales_lease_id,
            worker_id="worker-vertical-dependency-sales",
        )
        finish_session.commit()
    finally:
        finish_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id="worker-vertical-dependency-sales",
        tenant_id=tenant_id,
    ).execute(task_id=sales.id, lease_id=sales_lease_id)

    verify_session = session_factory()
    try:
        activate_tenant_session(verify_session, tenant_id)
        assert verify_session.get(ExecutionTask, research.id).status == ExecutionTaskState.COMPLETED.value  # type: ignore[union-attr]
        assert verify_session.get(ExecutionTask, sales.id).status == ExecutionTaskState.COMPLETED.value  # type: ignore[union-attr]
    finally:
        verify_session.close()
