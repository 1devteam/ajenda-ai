from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    tasks_queued: int
    tasks_completed: int
    tasks_failed: int
    dead_letter_count: int
    lease_expirations: int
    active_leases: int
    queued_tasks: int
    worker_utilization: float


class ObservabilityMetrics:
    def snapshot(
        self,
        *,
        tasks_queued: int,
        tasks_completed: int,
        tasks_failed: int,
        dead_letter_count: int,
        lease_expirations: int,
        active_leases: int,
        queued_tasks: int,
        worker_utilization: float,
    ) -> MetricsSnapshot:
        return MetricsSnapshot(
            tasks_queued=tasks_queued,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            dead_letter_count=dead_letter_count,
            lease_expirations=lease_expirations,
            active_leases=active_leases,
            queued_tasks=queued_tasks,
            worker_utilization=worker_utilization,
        )
