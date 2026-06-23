"""Runtime/worker admission Pydantic read models extracted from mission routes."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

RuntimeReadinessStatus = Literal["ready", "blocked", "incomplete"]
RuntimeReadinessCheckStatus = Literal["passed", "warning", "failed"]


class RuntimeReadinessItem(BaseModel):
    """One deterministic runtime readiness check, blocker, or warning."""

    code: str
    status: RuntimeReadinessCheckStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeReadinessRead(BaseModel):
    """Read-only runtime admission readiness validation result."""

    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["tenant_scoped_readiness_projection"] = "tenant_scoped_readiness_projection"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    ready: bool
    readiness_status: RuntimeReadinessStatus
    checked_at: str
    graph_reference: dict[str, Any] | None
    materialization_reference: dict[str, Any] | None
    admission_reference: dict[str, Any] | None
    selected_node_count: int
    checks: list[RuntimeReadinessItem]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]


RuntimeTaskPreviewStatus = Literal["ready", "blocked", "incomplete"]


class RuntimeTaskPreviewPayload(BaseModel):
    """Deterministic, non-persisted payload envelope preview for a future task."""

    mission_id: UUID
    graph_node_key: str
    graph_version: int | None
    graph_fingerprint: str | None
    materialization_version: int | None
    admission_version: int | None
    runtime_task_type: str
    input_contract: dict[str, Any]
    expected_output_contract: dict[str, Any]
    execution_constraints: dict[str, Any]


class RuntimeTaskPreviewItem(BaseModel):
    """One future ExecutionTask row preview; never persisted by this endpoint."""

    preview_task_key: str
    graph_node_key: str
    graph_node_name: str | None
    runtime_task_type: str
    future_execution_task_state: Literal["planned"] = "planned"
    payload_preview: RuntimeTaskPreviewPayload
    capability_reference: dict[str, Any] | None
    adapter_reference: dict[str, Any] | None
    materialization_selection_reference: dict[str, Any] | None
    dependency_keys: list[str]
    operator_notes: str | None


class RuntimeTaskPreviewRead(BaseModel):
    """Read-only preview of future runtime task materialization."""

    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["tenant_scoped_readiness_projection"] = "tenant_scoped_readiness_projection"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    ready: bool
    preview_status: RuntimeTaskPreviewStatus
    checked_at: str
    readiness_summary: dict[str, Any]
    task_count: int
    tasks: list[RuntimeTaskPreviewItem]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]
    runtime_authority: dict[str, bool]


RuntimeTaskMaterializationStatus = Literal["materialized", "blocked", "superseded"]
RuntimeDispatchReadinessStatus = Literal["ready", "partial", "blocked"]
WorkerDispatchEligibilityStatus = Literal["eligible", "partial", "blocked"]
WorkerClaimPreviewStatus = Literal["ready", "partial", "blocked"]
WorkerClaimAdmissionStatus = Literal["admitted", "partially_admitted", "blocked"]
WorkerStartAdmissionStatus = Literal["admitted", "partially_admitted", "blocked"]
WorkerRunAdmissionStatus = Literal["completed", "partially_completed", "failed", "blocked"]


class RuntimeTaskMaterializationRead(BaseModel):
    """ExecutionTask materialization response envelope for a mission graph admission."""

    authority_class: Literal["governed_mutation"] = "governed_mutation"
    side_effect_class: Literal["tenant_scoped_planned_task_creation"] = "tenant_scoped_planned_task_creation"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    materialization_status: RuntimeTaskMaterializationStatus
    materialization_version: int | None
    created_execution_task_ids: list[UUID]
    task_count: int
    graph_reference: dict[str, Any] | None
    materialization_reference: dict[str, Any] | None
    admission_reference: dict[str, Any] | None
    runtime_authority: dict[str, bool]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]
    updated_at: str


class RuntimeDispatchAuthority(BaseModel):
    """Negative authority flags for read-only dispatch readiness checks."""

    creates_execution_tasks: bool = False
    enqueues_work: bool = False
    dispatches_workers: bool = False
    calls_executor: bool = False
    calls_coordinator: bool = False
    executes_adapters: bool = False
    read_only: bool = True


class RuntimeDispatchReadinessRead(BaseModel):
    """Read-only readiness view for queued materialized task dispatch."""

    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["tenant_scoped_readiness_projection"] = "tenant_scoped_readiness_projection"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    readiness_status: RuntimeDispatchReadinessStatus
    dispatch_ready_task_ids: list[str]
    not_ready_task_ids: list[str]
    blocked_task_ids: list[str]
    skipped_task_ids: list[str]
    task_count: int
    queued_task_count: int
    materialization_reference: dict[str, Any] | None
    queue_admission_reference: dict[str, Any] | None
    runtime_authority: RuntimeDispatchAuthority
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    checked_at: str


class WorkerDispatchAuthority(BaseModel):
    """Negative authority flags for worker dispatch eligibility checks."""

    creates_worker_leases: bool = False
    claims_tasks: bool = False
    starts_execution: bool = False
    dispatches_workers: bool = False
    executes_handlers: bool = False
    enqueues_work: bool = False
    mutates_runtime_state: bool = False
    read_only: bool = True


class WorkerClaimAuthority(WorkerDispatchAuthority):
    """Negative authority flags for worker claim preview checks."""

    preview_only: bool = True


class WorkerDispatchEligibilityRead(BaseModel):
    """Read-only eligibility view for future worker claims."""

    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["tenant_scoped_readiness_projection"] = "tenant_scoped_readiness_projection"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    eligibility_status: WorkerDispatchEligibilityStatus
    eligible_task_ids: list[str]
    ineligible_task_ids: list[str]
    blocked_task_ids: list[str]
    skipped_task_ids: list[str]
    task_count: int
    queued_task_count: int
    materialization_reference: dict[str, Any] | None
    queue_admission_reference: dict[str, Any] | None
    dispatch_readiness_summary: dict[str, Any]
    worker_dispatch_authority: WorkerDispatchAuthority
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    checked_at: str


class WorkerClaimPreviewEnvelope(BaseModel):
    """Read-only preview of the future worker claim handoff envelope."""

    task_id: str
    tenant_id: str
    mission_id: str
    task_type: str
    current_task_state: str
    expected_claim_from_state: Literal["queued"] = "queued"
    future_claim_state: Literal["claimed"] = "claimed"
    worker_lease_required: bool = True
    lease_scope: dict[str, str]
    runtime_contract: dict[str, bool]
    source_references: dict[str, Any]
    task_metadata_summary: dict[str, Any]
    preview_only: bool = True


class WorkerClaimPreviewRead(BaseModel):
    """Read-only preview of future worker claim envelopes."""

    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["tenant_scoped_readiness_projection"] = "tenant_scoped_readiness_projection"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    preview_status: WorkerClaimPreviewStatus
    claim_preview_envelopes: list[WorkerClaimPreviewEnvelope]
    blocked_task_ids: list[str]
    skipped_task_ids: list[str]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    worker_claim_authority: WorkerClaimAuthority
    checked_at: str


class WorkerClaimReceipt(BaseModel):
    """Durable receipt for a worker claim admission decision."""

    task_id: str
    tenant_id: str
    mission_id: str
    previous_task_state: str
    current_task_state: str
    worker_lease_id: str | None = None
    lease_scope: dict[str, str]
    claim_source: Literal["worker_claim_admission"] = "worker_claim_admission"
    task_type: str | None = None
    claimed_at: str
    idempotency_status: Literal["newly_claimed", "already_claimed_by_current_admission", "blocked"]


class WorkerClaimAdmissionRead(BaseModel):
    """Tenant-scoped worker claim admission response and readback."""

    authority_class: Literal["governed_mutation"] = "governed_mutation"
    side_effect_class: Literal["tenant_scoped_task_state_transition"] = "tenant_scoped_task_state_transition"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    claim_admission_status: WorkerClaimAdmissionStatus
    claimed_task_ids: list[str]
    already_claimed_task_ids: list[str]
    skipped_task_ids: list[str]
    blocked_task_ids: list[str]
    claim_receipts: list[WorkerClaimReceipt]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    worker_claim_authority: WorkerClaimAuthority
    worker_claim_admission: dict[str, Any]
    updated_at: str


class WorkerStartAuthority(WorkerDispatchAuthority):
    """Authority flags for worker execution start admission."""

    read_only: bool = False


class WorkerRunAuthority(WorkerDispatchAuthority):
    """Authority flags for governed worker dispatcher execution admission."""

    executes_adapters: bool = False
    requires_queue_claim: bool = True
    completes_tasks: bool = False
    fails_tasks: bool = False
    read_only: bool = False


class WorkerStartReceipt(BaseModel):
    """Durable receipt for a worker execution start admission decision."""

    task_id: str
    tenant_id: str
    mission_id: str
    previous_task_state: str
    current_task_state: str
    worker_lease_id: str | None = None
    lease_scope: dict[str, str]
    start_source: Literal["worker_start_admission"] = "worker_start_admission"
    task_type: str | None = None
    started_at: str
    idempotency_status: Literal["newly_started", "already_started_by_current_admission", "blocked"]


class WorkerStartAdmissionRead(BaseModel):
    """Tenant-scoped worker execution start admission response and readback."""

    authority_class: Literal["governed_mutation"] = "governed_mutation"
    side_effect_class: Literal["tenant_scoped_task_state_transition"] = "tenant_scoped_task_state_transition"
    does_not_execute_runtime_work: bool = True
    mission_id: UUID
    tenant_id: str
    start_admission_status: WorkerStartAdmissionStatus
    started_task_ids: list[str]
    already_started_task_ids: list[str]
    skipped_task_ids: list[str]
    blocked_task_ids: list[str]
    start_receipts: list[WorkerStartReceipt]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    worker_start_authority: WorkerStartAuthority
    worker_start_admission: dict[str, Any]
    updated_at: str


class WorkerRunReceipt(BaseModel):
    """Durable receipt for governed dispatcher execution admission."""

    task_id: str
    tenant_id: str
    mission_id: str
    previous_task_state: str
    current_task_state: str
    worker_lease_id: str | None = None
    lease_scope: dict[str, str]
    queue_claim: dict[str, Any]
    run_source: Literal["worker_run_admission"] = "worker_run_admission"
    task_type: str
    handler_name: str | None = None
    handler_key: str | None = None
    started_from_admission_at: str | None = None
    retry_count: int | None = None
    attempt_identity: dict[str, Any] = Field(default_factory=dict)
    executed_at: str
    completed_at: str | None = None
    failed_at: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_summary: dict[str, Any] | None = None
    idempotency_status: Literal[
        "newly_executed",
        "already_completed_by_current_run_admission",
        "already_failed_by_current_run_admission",
        "blocked",
    ]


class WorkerRunAdmissionRead(BaseModel):
    """Tenant-scoped governed worker dispatcher execution response and readback."""

    authority_class: Literal["runtime_authoritative"] = "runtime_authoritative"
    side_effect_class: Literal["tenant_scoped_runtime_dispatch"] = "tenant_scoped_runtime_dispatch"
    does_not_execute_runtime_work: bool = False
    mission_id: UUID
    tenant_id: str
    run_admission_status: WorkerRunAdmissionStatus
    executed_task_ids: list[str]
    completed_task_ids: list[str]
    failed_task_ids: list[str]
    already_completed_task_ids: list[str]
    already_failed_task_ids: list[str]
    skipped_task_ids: list[str]
    blocked_task_ids: list[str]
    run_receipts: list[WorkerRunReceipt]
    queue_claim_receipts: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    worker_run_authority: WorkerRunAuthority
    worker_run_admission: dict[str, Any]
    updated_at: str
