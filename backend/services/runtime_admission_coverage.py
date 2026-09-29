"""Auditable inventory of every Ajenda runtime-work admission boundary.

This is a coverage contract, not a second runtime gate.  It records the
source-of-truth route/service for each mutating admission path and the
integrity/authority control that must protect it.  The validator fails closed
when a declared source or proof token disappears, so a newly moved admission
boundary cannot silently fall outside review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class RuntimeAdmissionCoverage:
    """One runtime-work admission boundary and its required proof anchors."""

    boundary_id: str
    kind: str
    source_path: str
    source_tokens: tuple[str, ...]
    authority_owner: str
    integrity_controls: tuple[str, ...]
    mutation_scope: str
    fail_closed: bool = True


RUNTIME_ADMISSION_COVERAGE: tuple[RuntimeAdmissionCoverage, ...] = (
    RuntimeAdmissionCoverage(
        boundary_id="mission.graph_runtime_admission",
        kind="route",
        source_path="backend/api/routes/mission.py",
        source_tokens=("def admit_mission_graph_to_runtime", "evaluate_admission_integrity"),
        authority_owner="runtime-admission-governance",
        integrity_controls=("GRAFT admission integrity", "tenant-scoped capability/adapter visibility"),
        mutation_scope="persist graph-to-runtime admission metadata only",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="mission.runtime_task_materialization",
        kind="route/service",
        source_path="backend/services/mission_runtime_task_materialization_service.py",
        source_tokens=("class MissionRuntimeTaskMaterializationService", "build_mission_runtime_readiness"),
        authority_owner="runtime-admission-governance",
        integrity_controls=("runtime readiness", "current graph/materialization/admission reference match"),
        mutation_scope="create planned tenant-scoped ExecutionTask rows; never queue",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="mission.runtime_queue_admission",
        kind="route/service",
        source_path="backend/services/mission_runtime_queue_admission_service.py",
        source_tokens=("class MissionRuntimeQueueAdmissionService", "ExecutionCoordinator"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("current materialization", "tenant-scoped queue admission", "ExecutionCoordinator"),
        mutation_scope="transition eligible tasks to queued and enqueue through coordinator",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="mission.legacy_queue_wrapper",
        kind="route",
        source_path="backend/api/routes/mission.py",
        source_tokens=("def queue_mission", "_admit_mission_runtime_queue"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("canonical runtime queue admission delegation",),
        mutation_scope="compatibility projection only; no alternate queue path",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="task.single_queue",
        kind="route",
        source_path="backend/api/routes/task.py",
        source_tokens=("def queue_task", "ExecutionCoordinator(db, queue).queue_task"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("tenant task ownership", "quota enforcement", "ExecutionCoordinator"),
        mutation_scope="queue one tenant-owned planned task",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="vertical_ops.template_queue",
        kind="route/service",
        source_path="backend/api/routes/vertical_ops.py",
        source_tokens=("def queue_applied_template_tasks", "service.queue_planned_tasks"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("template queue policy", "operating charter", "ExecutionCoordinator"),
        mutation_scope="queue previously applied vertical template tasks",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="admin.review_approval_queue",
        kind="route",
        source_path="backend/api/routes/admin.py",
        source_tokens=("def approve_task_review", "approve_review_and_queue"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("admin authorization", "pending_review state", "ExecutionCoordinator"),
        mutation_scope="approve and queue one reviewed task",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="mission.bridge_runtime_authority",
        kind="route/service",
        source_path="backend/services/mission_bridge_runtime_authority.py",
        source_tokens=("def provision_bridge_runtime_authority", "get_default_action_registry"),
        authority_owner="capability-runtime-governance",
        integrity_controls=("ActionRegistry resolution", "tenant-scoped capability and adapter authority"),
        mutation_scope="provision declarative capability/adapter authority; never dispatch",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="worker.claim_start",
        kind="daemon",
        source_path="backend/services/worker_runtime_service.py",
        source_tokens=("def claim_next_task", "def start_execution"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("lease ownership", "worker runtime state"),
        mutation_scope="claim and start only lease-owned queued work",
    ),
    RuntimeAdmissionCoverage(
        boundary_id="worker.dispatcher",
        kind="daemon",
        source_path="backend/workers/worker_loop.py",
        source_tokens=("TaskDispatcher", "dispatcher.execute"),
        authority_owner="runtime-execution-governance",
        integrity_controls=("lease ownership", "TaskDispatcher"),
        mutation_scope="dispatch only lease-owned started work",
    ),
)


def validate_runtime_admission_coverage(*, repo_root: Path = REPO_ROOT) -> None:
    """Fail closed when an admission boundary loses its declared proof anchor."""

    seen: set[str] = set()
    for boundary in RUNTIME_ADMISSION_COVERAGE:
        if boundary.boundary_id in seen:
            raise ValueError(f"duplicate runtime admission boundary: {boundary.boundary_id}")
        seen.add(boundary.boundary_id)
        if not boundary.fail_closed:
            raise ValueError(f"runtime admission boundary is not fail-closed: {boundary.boundary_id}")
        if not boundary.integrity_controls:
            raise ValueError(f"runtime admission boundary has no integrity controls: {boundary.boundary_id}")
        source_path = repo_root / boundary.source_path
        if not source_path.is_file():
            raise ValueError(f"runtime admission source is missing: {boundary.source_path}")
        source = source_path.read_text(encoding="utf-8")
        missing = [token for token in boundary.source_tokens if token not in source]
        if missing:
            raise ValueError(f"runtime admission proof tokens missing for {boundary.boundary_id}: {missing}")


validate_runtime_admission_coverage()
