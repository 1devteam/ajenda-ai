"""Observability routes — Prometheus metrics and lineage endpoints.

The /observability/metrics endpoint is mounted under /v1/ by the API router,
making the full path /v1/observability/metrics. The ServiceMonitor and
AuthContextMiddleware public-path allowlist both reference this path.

Metrics are computed by querying the live database for current task and lease
counts. This is a lightweight read-only operation (COUNT queries with index
scans on status columns). For high-traffic deployments, consider caching the
snapshot for 15-30 seconds to match the Prometheus scrape interval.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.assurance_snapshot import AssuranceMetricState
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.metrics.prometheus_exporter import PrometheusExporter
from backend.observability.metrics import MetricsSnapshot
from backend.repositories.assurance_snapshot_repository import AssuranceSnapshotRepository
from backend.services.observability_service import ObservabilityService

logger = logging.getLogger("ajenda.observability")
router = APIRouter()

_exporter = PrometheusExporter()


class ReliabilityLeaseHealthRead(BaseModel):
    """Read-only queue lease health indicator summary."""

    model_config = ConfigDict(extra="forbid")

    active_leases: int = Field(ge=0)
    expired_leases: int = Field(ge=0)
    released_leases: int = Field(ge=0)
    lease_expiration_rate: float = Field(ge=0.0, le=1.0)


class ReliabilityRecoveryRead(BaseModel):
    """Read-only bounded recovery posture summary."""

    model_config = ConfigDict(extra="forbid")

    recovered_tasks: int = Field(ge=0)
    dead_lettered_tasks: int = Field(ge=0)
    recovery_success_ratio: float = Field(ge=0.0, le=1.0)


class TenantReliabilitySummaryRead(BaseModel):
    """Read-only tenant reliability projection for runtime posture."""

    model_config = ConfigDict(extra="forbid")

    authority_class: str = "read_model"
    side_effect_class: str = "none"
    does_not_execute_runtime_work: bool = True
    mission_throughput_total: int = Field(ge=0)
    mission_throughput_completed: int = Field(ge=0)
    mission_throughput_failed: int = Field(ge=0)
    mission_throughput_success_rate: float = Field(ge=0.0, le=1.0)
    dead_letter_rate: float = Field(ge=0.0, le=1.0)
    lease_health: ReliabilityLeaseHealthRead
    recovery: ReliabilityRecoveryRead


def _collect_snapshot(session: Session) -> MetricsSnapshot:
    """Query the database for current metric values and return a MetricsSnapshot.

    All queries are simple COUNT aggregations on indexed status columns.
    They run in a single read-only transaction (no writes).
    """

    def _count_tasks(status: str) -> int:
        result = session.execute(select(func.count()).where(ExecutionTask.status == status))
        return result.scalar_one()

    def _count_leases(status: str) -> int:
        result = session.execute(select(func.count()).where(WorkerLease.status == status))
        return result.scalar_one()

    tasks_queued = _count_tasks(ExecutionTaskState.QUEUED.value)
    tasks_completed = _count_tasks(ExecutionTaskState.COMPLETED.value)
    tasks_failed = _count_tasks(ExecutionTaskState.FAILED.value)
    dead_letter_count = _count_tasks(ExecutionTaskState.DEAD_LETTERED.value)

    # Lease expirations: count all leases in EXPIRED state (cumulative)
    lease_expirations = _count_leases(WorkerLeaseState.EXPIRED.value)

    # Active leases: leases currently in CLAIMED or ACTIVE state
    active_claimed = _count_leases(WorkerLeaseState.CLAIMED.value)
    active_active = _count_leases(WorkerLeaseState.ACTIVE.value)
    active_leases = active_claimed + active_active

    # Worker utilization: active_leases / max(active_leases + released, 1)
    released_leases = _count_leases(WorkerLeaseState.RELEASED.value)
    total_leases = active_leases + released_leases
    worker_utilization = round(active_leases / total_leases, 4) if total_leases > 0 else 0.0

    assurance = session.get(AssuranceMetricState, 1)
    return MetricsSnapshot(
        tasks_queued=tasks_queued,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        dead_letter_count=dead_letter_count,
        lease_expirations=lease_expirations,
        active_leases=active_leases,
        queued_tasks=tasks_queued,  # alias for backward compat
        worker_utilization=worker_utilization,
        assurance_snapshot_count=assurance.snapshot_count if assurance is not None else 0,
        assurance_incomplete_count=assurance.incomplete_count if assurance is not None else 0,
        assurance_drifted_count=assurance.drifted_count if assurance is not None else 0,
        assurance_contradictory_count=assurance.contradictory_count if assurance is not None else 0,
        assurance_first_divergence_count=assurance.first_divergence_count if assurance is not None else 0,
        assurance_calibration_sample_count=assurance.calibration_sample_count if assurance is not None else 0,
        assurance_calibration_aligned_count=assurance.calibration_aligned_count if assurance is not None else 0,
    )


@router.get(
    "/observability/metrics",
    summary="Prometheus metrics scrape endpoint",
    description=(
        "Returns current runtime metrics in Prometheus text exposition format. "
        "Scraped by the Prometheus ServiceMonitor at /v1/observability/metrics. "
        "This endpoint is exempt from authentication (public path allowlist in AuthContextMiddleware)."
    ),
    response_class=Response,
    include_in_schema=True,
)
def metrics(session: Session = Depends(get_db_session)) -> Response:
    """Return Prometheus text format metrics from live DB queries."""
    try:
        snapshot = _collect_snapshot(session)
    except Exception:
        logger.exception("metrics_collection_failed")
        # Return a minimal safe response rather than 500 — Prometheus will
        # record a scrape failure but the application remains healthy.
        return Response(
            content="# metrics collection failed\najenda_up 0\n",
            media_type="text/plain; version=0.0.4",
            status_code=200,
        )

    content = _exporter.render(snapshot)
    return Response(content=content, media_type="text/plain; version=0.0.4")


@router.get("/observability/reliability/summary", response_model=TenantReliabilitySummaryRead)
def tenant_reliability_summary(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> TenantReliabilitySummaryRead:
    """Return tenant-scoped read-only runtime reliability summary."""
    require_route_permission(request=request, db=session, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    service = ObservabilityService(session)
    snapshot = service.metrics_snapshot(tenant_id=str(tenant_id))
    total_terminal = snapshot.tasks_completed + snapshot.tasks_failed
    throughput_total = total_terminal + snapshot.tasks_queued
    throughput_success_rate = float(snapshot.tasks_completed) / float(max(total_terminal, 1))
    dead_letter_denominator = total_terminal + snapshot.dead_letter_count
    dead_letter_rate = float(snapshot.dead_letter_count) / float(max(dead_letter_denominator, 1))
    expired_leases = int(snapshot.lease_expirations)
    released_leases = int(snapshot.released_leases)
    lease_expiration_rate = float(expired_leases) / float(max(snapshot.active_leases + expired_leases, 1))
    recovered_tasks = max(expired_leases - snapshot.dead_letter_count, 0)
    recovery_success_ratio = float(recovered_tasks) / float(max(recovered_tasks + snapshot.dead_letter_count, 1))
    return TenantReliabilitySummaryRead(
        mission_throughput_total=throughput_total,
        mission_throughput_completed=snapshot.tasks_completed,
        mission_throughput_failed=snapshot.tasks_failed,
        mission_throughput_success_rate=round(throughput_success_rate, 4),
        dead_letter_rate=round(dead_letter_rate, 4),
        lease_health=ReliabilityLeaseHealthRead(
            active_leases=snapshot.active_leases,
            expired_leases=expired_leases,
            released_leases=released_leases,
            lease_expiration_rate=round(lease_expiration_rate, 4),
        ),
        recovery=ReliabilityRecoveryRead(
            recovered_tasks=recovered_tasks,
            dead_lettered_tasks=snapshot.dead_letter_count,
            recovery_success_ratio=round(recovery_success_ratio, 4),
        ),
    )




class AssuranceSnapshotRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: _uuid.UUID
    mission_id: _uuid.UUID
    status: str
    first_divergence: str | None
    finding_count: int
    findings: list[dict[str, object]]
    runtime_summary: dict[str, object]
    reconciliation_summary: dict[str, object]
    epistemic_confidence: float | None
    calibration_eligible: bool
    calibration_outcome_aligned: bool | None
    observed_at: str
    authority_class: str = "read_model"
    grants_execution_authority: bool = False


class AssuranceSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_count: int
    aligned_count: int
    incomplete_count: int
    drifted_count: int
    contradictory_count: int
    first_divergence_count: int
    calibration_sample_count: int
    calibration_aligned_count: int
    calibration_alignment_rate: float | None
    authority_class: str = "read_model"
    grants_execution_authority: bool = False


@router.get("/observability/assurance/history", response_model=list[AssuranceSnapshotRead])
def assurance_history(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
    limit: int = 100,
) -> list[AssuranceSnapshotRead]:
    """Return append-only tenant assurance history without runtime mutation."""

    require_route_permission(request=request, db=session, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    rows = AssuranceSnapshotRepository(session).list_for_tenant(tenant_id=str(tenant_id), limit=limit)
    return [
        AssuranceSnapshotRead(
            snapshot_id=row.id,
            mission_id=row.mission_id,
            status=row.status,
            first_divergence=row.first_divergence,
            finding_count=row.finding_count,
            findings=list(row.findings or []),
            runtime_summary=dict(row.runtime_summary or {}),
            reconciliation_summary=dict(row.reconciliation_summary or {}),
            epistemic_confidence=row.epistemic_confidence,
            calibration_eligible=row.calibration_eligible,
            calibration_outcome_aligned=row.calibration_outcome_aligned,
            observed_at=row.observed_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/observability/assurance/summary", response_model=AssuranceSummaryRead)
def assurance_summary(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> AssuranceSummaryRead:
    """Return metrics from the latest assurance observation for each tenant mission."""

    require_route_permission(request=request, db=session, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    rows = AssuranceSnapshotRepository(session).list_for_tenant(tenant_id=str(tenant_id), limit=500)
    latest_by_mission = {}
    for row in rows:
        latest_by_mission.setdefault(row.mission_id, row)
    latest = list(latest_by_mission.values())
    calibration = [row for row in latest if row.calibration_eligible]
    calibration_aligned = sum(row.calibration_outcome_aligned is True for row in calibration)
    return AssuranceSummaryRead(
        mission_count=len(latest),
        aligned_count=sum(row.status == "aligned" for row in latest),
        incomplete_count=sum(row.status == "incomplete" for row in latest),
        drifted_count=sum(row.status == "drifted" for row in latest),
        contradictory_count=sum(row.status == "contradictory" for row in latest),
        first_divergence_count=sum(row.first_divergence is not None for row in latest),
        calibration_sample_count=len(calibration),
        calibration_aligned_count=calibration_aligned,
        calibration_alignment_rate=(
            round(calibration_aligned / len(calibration), 4) if calibration else None
        ),
    )


@router.get("/observability/compliance/export")
def compliance_export(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
    limit: int = 100,
) -> dict[str, object]:
    """Compliance export foundation: tenant-scoped recent audit and evidence records.

    Read-only, for audit/compliance review. Tenant-scoped.
    """
    require_route_permission(request=request, db=session, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    service = ObservabilityService(session)
    return service.compliance_export(tenant_id=str(tenant_id), limit=limit)
