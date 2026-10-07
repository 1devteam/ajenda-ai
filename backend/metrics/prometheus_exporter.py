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
        tenant_label = f'tenant_id="{snapshot.tenant_id}"' if snapshot.tenant_id else ""
        base_label = f"{{{tenant_label}}}" if tenant_label else ""
        lines = [
            "# TYPE ajenda_tasks_queued gauge",
            f"ajenda_tasks_queued{base_label} {snapshot.tasks_queued}",
            "# TYPE ajenda_tasks_completed counter",
            f"ajenda_tasks_completed{base_label} {snapshot.tasks_completed}",
            "# TYPE ajenda_tasks_failed counter",
            f"ajenda_tasks_failed{base_label} {snapshot.tasks_failed}",
            "# TYPE ajenda_dead_letter_count gauge",
            f"ajenda_dead_letter_count{base_label} {snapshot.dead_letter_count}",
            "# TYPE ajenda_queue_depth gauge",
            f"ajenda_queue_depth{base_label} {snapshot.queued_tasks}",
            "# TYPE ajenda_lease_expirations counter",
            f"ajenda_lease_expirations{base_label} {snapshot.lease_expirations}",
            "# TYPE ajenda_active_leases gauge",
            f"ajenda_active_leases{base_label} {snapshot.active_leases}",
            "# TYPE ajenda_worker_utilization gauge",
            f"ajenda_worker_utilization{base_label} {snapshot.worker_utilization}",
            "# TYPE ajenda_assurance_snapshot_count gauge",
            f"ajenda_assurance_snapshot_count {snapshot.assurance_snapshot_count}",
            "# TYPE ajenda_assurance_incomplete_count gauge",
            f"ajenda_assurance_incomplete_count {snapshot.assurance_incomplete_count}",
            "# TYPE ajenda_assurance_drifted_count gauge",
            f"ajenda_assurance_drifted_count {snapshot.assurance_drifted_count}",
            "# TYPE ajenda_assurance_contradictory_count gauge",
            f"ajenda_assurance_contradictory_count {snapshot.assurance_contradictory_count}",
            "# TYPE ajenda_assurance_first_divergence_count gauge",
            f"ajenda_assurance_first_divergence_count {snapshot.assurance_first_divergence_count}",
            "# TYPE ajenda_assurance_calibration_sample_count gauge",
            f"ajenda_assurance_calibration_sample_count {snapshot.assurance_calibration_sample_count}",
            "# TYPE ajenda_assurance_calibration_aligned_count gauge",
            f"ajenda_assurance_calibration_aligned_count {snapshot.assurance_calibration_aligned_count}",
            "# TYPE ajenda_assurance_scan_failure_count gauge",
            f"ajenda_assurance_scan_failure_count {snapshot.assurance_tenant_failure_count}",
            "# HELP ajenda_stage_budget_limit Observed stage budget limits (observe-only scaffolding).",
            "# TYPE ajenda_stage_budget_limit gauge",
            f'ajenda_stage_budget_limit{{stage="runtime",budget_kind="cost_usd"{"," + tenant_label if tenant_label else ""}}} {snapshot.stage_budget_limit_cost_usd}',
            (
                f'ajenda_stage_budget_limit{{stage="runtime",budget_kind="runtime_minutes"{"," + tenant_label if tenant_label else ""}}} '
                f"{snapshot.stage_budget_limit_runtime_minutes}"
            ),
            "# HELP ajenda_stage_budget_spend Observed stage budget spend (observe-only scaffolding).",
            "# TYPE ajenda_stage_budget_spend gauge",
            f'ajenda_stage_budget_spend{{stage="runtime",budget_kind="cost_usd"{"," + tenant_label if tenant_label else ""}}} {snapshot.stage_budget_spend_cost_usd}',
            (
                f'ajenda_stage_budget_spend{{stage="runtime",budget_kind="runtime_minutes"{"," + tenant_label if tenant_label else ""}}} '
                f"{snapshot.stage_budget_spend_runtime_minutes}"
            ),
            "# HELP ajenda_stage_budget_breach_total Count of stage budget breach observations.",
            "# TYPE ajenda_stage_budget_breach_total counter",
            f'ajenda_stage_budget_breach_total{{stage="runtime",budget_kind="any"{"," + tenant_label if tenant_label else ""}}} {snapshot.stage_budget_breach_total}',
            f"# HELP {READINESS_METRIC_NAME} Runtime dependency readiness status.",
            f"# TYPE {READINESS_METRIC_NAME} gauge",
        ]
        for dependency, value in readiness_dependency_samples():
            dep_label = f'{{dependency="{dependency}"{"," + tenant_label if tenant_label else ""}}}'
            lines.append(f"{READINESS_METRIC_NAME}{dep_label} {value}")
        return "\n".join(lines) + "\n"
