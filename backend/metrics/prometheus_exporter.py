from __future__ import annotations

from backend.observability.metrics import MetricsSnapshot


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
            "# TYPE ajenda_lease_expirations counter",
            f"ajenda_lease_expirations {snapshot.lease_expirations}",
            "# TYPE ajenda_active_leases gauge",
            f"ajenda_active_leases {snapshot.active_leases}",
            "# TYPE ajenda_worker_utilization gauge",
            f"ajenda_worker_utilization {snapshot.worker_utilization}",
        ]
        return "\n".join(lines) + "\n"
