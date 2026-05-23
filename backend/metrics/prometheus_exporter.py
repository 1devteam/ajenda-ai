from __future__ import annotations

from backend.observability.metrics import MetricsSnapshot

READINESS_METRIC_NAME = "ajenda_readiness_dependency_status"
READINESS_DEPENDENCIES = ("database", "queue")


_readiness_dependency_values: dict[str, int] = {dependency: 0 for dependency in READINESS_DEPENDENCIES}


def reset_readiness_dependency_statuses() -> None:
    for dependency in READINESS_DEPENDENCIES:
        _readiness_dependency_values[dependency] = 0


def set_readiness_dependency_status(*, dependency: str, status: str) -> None:
    if dependency not in READINESS_DEPENDENCIES:
        return
    _readiness_dependency_values[dependency] = 0 if status == "unavailable" else 1


def readiness_dependency_samples() -> list[tuple[str, int]]:
    return [(dependency, _readiness_dependency_values[dependency]) for dependency in READINESS_DEPENDENCIES]


class PrometheusExporter:
    def render(self, snapshot: MetricsSnapshot) -> str:
        lines = [
            "# TYPE ajenda_tasks_queued gauge",
            f"ajenda_tasks_queued {snapshot.tasks_queued}",
            "# TYPE ajenda_tasks_completed counter",
            f"ajenda_tasks_completed {snapshot.tasks_completed}",
            "# TYPE ajenda_tasks_failed counter",
            f"ajenda_tasks_failed {snapshot.tasks_failed}",
            "# TYPE ajenda_dead_letter_count gauge",
            f"ajenda_dead_letter_count {snapshot.dead_letter_count}",
            "# TYPE ajenda_queue_depth gauge",
            f"ajenda_queue_depth {snapshot.queued_tasks}",
            "# TYPE ajenda_lease_expirations counter",
            f"ajenda_lease_expirations {snapshot.lease_expirations}",
            "# TYPE ajenda_active_leases gauge",
            f"ajenda_active_leases {snapshot.active_leases}",
            "# TYPE ajenda_worker_utilization gauge",
            f"ajenda_worker_utilization {snapshot.worker_utilization}",
            f"# HELP {READINESS_METRIC_NAME} Runtime dependency readiness status.",
            f"# TYPE {READINESS_METRIC_NAME} gauge",
        ]
        for dependency, value in readiness_dependency_samples():
            lines.append(f'{READINESS_METRIC_NAME}{{dependency="{dependency}"}} {value}')
        return "\n".join(lines) + "\n"
