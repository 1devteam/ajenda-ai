"""Worker lease holder identity contract for queue claim paths."""

from __future__ import annotations

from uuid import UUID


def worker_daemon_holder(*, worker_id: str) -> str:
    """Holder identity used by WorkerLoop claim_next_task polling."""
    normalized = worker_id.strip()
    if not normalized:
        raise ValueError("worker_id must be non-empty for daemon claim holder")
    return normalized


def worker_bridge_holder(*, tenant_id: str, mission_id: UUID) -> str:
    """Holder identity used by HTTP worker-run-admission synchronous dispatch."""
    tenant = tenant_id.strip()
    if not tenant:
        raise ValueError("tenant_id must be non-empty for bridge claim holder")
    return f"worker_claim_admission:{tenant}:{mission_id}"
