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
    released_leases: int = 0
    stage_budget_limit_cost_usd: float = 0.0
    stage_budget_spend_cost_usd: float = 0.0
    stage_budget_limit_runtime_minutes: float = 0.0
    stage_budget_spend_runtime_minutes: float = 0.0
    stage_budget_breach_total: int = 0


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
        released_leases: int = 0,
        stage_budget_limit_cost_usd: float = 0.0,
        stage_budget_spend_cost_usd: float = 0.0,
        stage_budget_limit_runtime_minutes: float = 0.0,
        stage_budget_spend_runtime_minutes: float = 0.0,
        stage_budget_breach_total: int = 0,
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
            released_leases=released_leases,
            stage_budget_limit_cost_usd=stage_budget_limit_cost_usd,
            stage_budget_spend_cost_usd=stage_budget_spend_cost_usd,
            stage_budget_limit_runtime_minutes=stage_budget_limit_runtime_minutes,
            stage_budget_spend_runtime_minutes=stage_budget_spend_runtime_minutes,
            stage_budget_breach_total=stage_budget_breach_total,
        )
