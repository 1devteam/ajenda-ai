from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.audit_event import AuditEvent
from backend.domain.business_profile import BusinessProfile
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY, Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.runtime_governance import AbilityAuthorizationV1, manifest_fingerprint
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_bridge.queue_admission import build_runtime_queue_admission_metadata
from backend.services.operating_charter import OperatingCharter
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    SideEffectClass,
    ToolInvocation,
    tool_invocation_sha256,
)
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration


def test_revoked_browser_approval_is_denied_at_final_runtime_boundary_before_provider(
    pg_engine, queue_adapter, monkeypatch
) -> None:
    """A reviewed browser task cannot execute after its task-bound grant is revoked."""

    from backend.services import execution_coordinator
    from backend.services.tools import runtime_authority

    tenant_id = str(uuid.uuid4())
    worker_id = "worker-browser-governance-revocation-real"
    provider_calls: list[str] = []
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def fake_browser_provider(invocation: ToolInvocation, _context: ActionRuntimeContext) -> ActionResult:
        provider_calls.append(invocation.action)
        return ActionResult(
            action=invocation.action,
            provider="fake_browser_provider",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            output={"unexpected": True},
            evidence=[],
            summary="must not be invoked after approval revocation",
        )

    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="web.browser_session",
            handler=fake_browser_provider,
            provider="ajenda_internet",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.freeze()
    manifest = ABILITY_MANIFESTS_BY_ACTION["web.browser_session"]
    monkeypatch.setattr(execution_coordinator, "get_default_action_registry", lambda: registry)
    monkeypatch.setattr(runtime_authority, "get_default_action_registry", lambda: registry)
    monkeypatch.setattr(
        runtime_authority.ToolRuntimeAuthority,
        "_validate_ability_manifest",
        staticmethod(lambda _action: manifest),
    )
    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **_kwargs: None)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id), name="Browser Governance Tenant", slug=f"browser-{tenant_id[:8]}", plan="free"
            )
        )
        mission = Mission(tenant_id=tenant_id, objective="Review browser observation", status="running")
        setup_session.add(mission)
        setup_session.flush()
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Reviewed browser observation",
            description="Must be stopped when review authority is revoked",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "web.browser_session",
                    "input": {"url": "https://example.test"},
                },
                "capability_reference": {"capability_id": str(uuid.uuid4())},
                "adapter_reference": {"adapter_id": str(uuid.uuid4())},
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id
        coordinator = ExecutionCoordinator(setup_session, queue_adapter)
        held = coordinator.queue_task(tenant_id=tenant_id, task_id=task_id)
        assert held.ok is False
        assert held.state == ExecutionTaskState.PENDING_REVIEW.value
        # This direct task fixture still has to satisfy the same durable
        # mission-admission receipt that the mission admission service writes
        # before a reviewer can release a task to the queue.
        mission.metadata_json = {
            MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY: build_runtime_queue_admission_metadata(
                mission_id=mission.id,
                tenant_id=tenant_id,
                materialized_task_ids=[task_id],
                planned_task_ids=[str(task_id)],
                queued_task_ids=[],
                already_queued_task_ids=[],
                pending_review_task_ids=[str(task_id)],
                denied_tasks=[],
                blockers=[
                    {
                        "task_id": str(task_id),
                        "code": "policy_review_required",
                        "message": "Execution coordinator routed the materialized task to policy review.",
                        "state": ExecutionTaskState.PENDING_REVIEW.value,
                        "reason": held.reason,
                    }
                ],
                now=datetime.now(UTC).isoformat(),
            )
        }
        approved = coordinator.approve_review_and_queue(
            tenant_id=tenant_id,
            task_id=task_id,
            actor="human:browser-reviewer",
            approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert approved.ok is True
        revoked = coordinator.revoke_side_effect_approval(
            tenant_id=tenant_id,
            task_id=task_id,
            actor="human:browser-reviewer",
            reason="review scope withdrawn",
        )
        assert revoked.reason == "approval_revoked"
        setup_session.commit()

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory, queue=queue_adapter, worker_id=worker_id, tenant_id=tenant_id
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        denials = verify_session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.mission_id == mission.id,
                AuditEvent.category == "ability_governance",
                AuditEvent.action == "ability_approval_denied_at_execution",
            )
        ).all()
        assert provider_calls == []
        assert final_task is not None
        assert final_task.status == ExecutionTaskState.FAILED.value
        assert len(denials) == 1
        assert denials[0].payload_json["reason_code"] == "human_approval_missing_or_invalid"
        assert denials[0].payload_json["enforcement_boundary"] == "pre_provider_invocation"
        assert "url" not in denials[0].payload_json
        assert "credential" not in denials[0].payload_json
    finally:
        verify_session.close()


def test_worker_executes_tool_invoke_task_and_persists_evidence_shaped_output(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-tool-real"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(id=uuid.UUID(tenant_id), name="Tool Tenant", slug=f"tool-{tenant_id[:8]}", plan="free")
        )
        mission = Mission(tenant_id=tenant_id, objective="Tool mission", status="running")
        setup_session.add(mission)
        setup_session.flush()
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Tool invoke task",
            description="Task proves real tool.invoke execution through dispatcher",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "record.search",
                    "input": {"record_type": "account", "query": "Ajenda"},
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)
        assert queued.ok is True
        setup_session.commit()
        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory, queue=queue_adapter, worker_id=worker_id, tenant_id=tenant_id
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
                EvidenceRecord.evidence_source == "tool.invoke.record.search",
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_task.metadata_json["handler_result"]["handler"] == "tool.invoke"
        assert final_task.metadata_json["output"]["count"] >= 1
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        payload = lineage[0].metadata_json
        assert lineage[0].relationship_reason == "tool action completed"
        assert payload["handler"] == "tool.invoke"
        assert payload["action"] == "record.search"
        assert payload["output"]["count"] >= 1
        assert payload["evidence"][0]["action_name"] == "record.search"
        assert payload["evidence"][0]["tenant_id"] == tenant_id
        assert len(evidence_records) == 1
        evidence = evidence_records[0]
        assert evidence.mission_id == final_task.mission_id
        assert evidence.evidence_type == "execution_trace"
        assert evidence.provenance_metadata["tool_evidence_type"] == "action_result"
        assert evidence.structured_payload["count"] >= 1
        assert evidence.materialization_reference["lineage_record_id"] == str(lineage[0].id)
        assert evidence.artifact_references[0]["lineage_record_id"] == str(lineage[0].id)
        assert redis_client.hlen(f"ajenda:queue:{tenant_id}:v2:processing-payloads") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()


def test_queued_external_write_is_denied_after_charter_revocation_before_fake_provider(
    pg_engine, queue_adapter, monkeypatch
) -> None:
    """A queued external write must reread the active charter before dispatch."""
    from backend.repositories.business_profile_repository import BusinessProfileRepository
    from backend.services.tools import runtime_authority

    tenant_id = str(uuid.uuid4())
    worker_id = "worker-charter-revocation-real"
    provider_calls: list[str] = []
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def fake_provider(invocation: ToolInvocation, _context: ActionRuntimeContext) -> ActionResult:
        provider_calls.append(invocation.action)
        return ActionResult(
            action=invocation.action,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            output={"sent": True},
            evidence=[],
            summary="fake external provider invoked",
        )

    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="web.open_write",
            handler=fake_provider,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        )
    )
    registry.freeze()
    monkeypatch.setattr(runtime_authority, "get_default_action_registry", lambda: registry)
    monkeypatch.setattr(
        runtime_authority.ToolRuntimeAuthority,
        "_validate_ability_manifest",
        staticmethod(lambda _action: None),
    )
    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **_kwargs: None)

    allowed_charter = OperatingCharter(
        schema_version=1,
        revision=1,
        may_prepare=(),
        may_perform=("web.open_write",),
        never_do=("gtm.email_send", "gtm.social_publish", "webhook.dispatch"),
        approval_mode="none",
        escalation_email=None,
        escalation_phone=None,
        source="profile",
    )
    revoked_charter = OperatingCharter(
        schema_version=1,
        revision=1,
        may_prepare=(),
        may_perform=(),
        never_do=("gtm.email_send", "gtm.social_publish", "webhook.dispatch"),
        approval_mode="none",
        escalation_email=None,
        escalation_phone=None,
        source="profile",
    )

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(id=uuid.UUID(tenant_id), name="Charter Runtime Tenant", slug=f"charter-{tenant_id[:8]}", plan="free")
        )
        setup_session.add(
            BusinessProfile(
                tenant_id=tenant_id,
                approved_facts={"operating_charter": {"value": allowed_charter.to_fact_payload()}},
                provenance={},
            )
        )
        mission = Mission(tenant_id=tenant_id, objective="Queued external write", status="running")
        setup_session.add(mission)
        setup_session.flush()
        invocation = {
            "schema_version": 1,
            "action": "web.open_write",
            "input": {
                "url": "https://example.com/charter-proof",
                "method": "POST",
                "idempotency_key": f"charter-proof-{uuid.uuid4().hex}",
            },
        }
        task_id = uuid.uuid4()
        manifest = ABILITY_MANIFESTS_BY_ACTION["web.open_write"]
        approved_at = datetime.now(UTC)
        task = ExecutionTask(
            id=task_id,
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Queued external write",
            description="Must be stopped by current charter before provider invocation",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": invocation,
                # This represents a valid independent approval created before
                # the charter was revoked. The runtime must still deny it.
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 2,
                        "grant_id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "task_id": str(task_id),
                        "allowed_action": "web.open_write",
                        "invocation_sha256": tool_invocation_sha256(invocation),
                        "reason": "human_review_approved",
                        "approved_by": "admin:charter-proof",
                        "approved_at": datetime.now(UTC).isoformat(),
                        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                        "revoked_at": None,
                    },
                    "ability_authorization": AbilityAuthorizationV1(
                        grant_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        task_id=task_id,
                        ability_id=manifest.ability_id,
                        manifest_fingerprint=manifest_fingerprint(manifest),
                        allowed_action=manifest.action_name,
                        invocation_sha256=tool_invocation_sha256(invocation),
                        reason="human_review_approved",
                        approved_by="admin:charter-proof",
                        approved_at=approved_at,
                        expires_at=approved_at + timedelta(hours=1),
                    ).model_dump(mode="json"),
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)
        assert queued.ok is True
        setup_session.commit()

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    revoke_session = session_factory()
    try:
        activate_tenant_session(revoke_session, tenant_id)
        repo = BusinessProfileRepository(revoke_session)
        profile = repo.get_active_profile_for_tenant(tenant_id=tenant_id)
        assert profile is not None
        repo.upsert_operating_charter(
            profile=profile,
            charter=revoked_charter,
            expected_revision=1,
            actor_id="charter-admin",
            updated_at=profile.updated_at,
        )
        revoke_session.commit()
    finally:
        revoke_session.close()

    TaskDispatcher(
        session_factory=session_factory, queue=queue_adapter, worker_id=worker_id, tenant_id=tenant_id
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        denials = verify_session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.mission_id == task.mission_id,
                AuditEvent.category == "operating_charter",
                AuditEvent.action == "side_effect_denied_at_execution",
            )
        ).all()
        assert provider_calls == []
        assert final_task is not None
        assert final_task.status == ExecutionTaskState.FAILED.value
        assert len(denials) == 1
        assert denials[0].payload_json["reason_code"] == "CHARTER_PERFORM_NOT_ALLOWED"
        assert denials[0].payload_json["enforcement_boundary"] == "pre_provider_invocation"
    finally:
        verify_session.close()
