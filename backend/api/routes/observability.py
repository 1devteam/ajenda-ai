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

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.metrics.prometheus_exporter import PrometheusExporter
from backend.observability.metrics import MetricsSnapshot

logger = logging.getLogger("ajenda.observability")
router = APIRouter()

_exporter = PrometheusExporter()


def _collect_snapshot(session: Session) -> MetricsSnapshot:
    """Query the database for current metric values and return a MetricsSnapshot.

    All queries are simple COUNT aggregations on indexed status columns.
    They run in a single read-only transaction (no writes).
    """

    def _count_tasks(status: str) -> int:
        result = session.execute(
            select(func.count()).where(ExecutionTask.status == status)
        )
        return result.scalar_one()

    def _count_leases(status: str) -> int:
        result = session.execute(
            select(func.count()).where(WorkerLease.status == status)
        )
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

    return MetricsSnapshot(
        tasks_queued=tasks_queued,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        dead_letter_count=dead_letter_count,
        lease_expirations=lease_expirations,
        active_leases=active_leases,
        queued_tasks=tasks_queued,  # alias for backward compat
        worker_utilization=worker_utilization,
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
