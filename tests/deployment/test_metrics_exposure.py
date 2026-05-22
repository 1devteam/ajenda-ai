from pathlib import Path


def test_metrics_scrape_path_is_exposed() -> None:
    """The ServiceMonitor must reference the correct versioned path.

    The observability router is mounted under /v1/ by build_api_router(),
    so the full scrape path is /v1/observability/metrics, not /observability/metrics.
    """
    content = Path("deploy/k8s/prometheus-servicemonitor.yaml").read_text(encoding="utf-8")
    assert "/v1/observability/metrics" in content


def test_compose_prometheus_uses_versioned_observability_metrics_path() -> None:
    content = Path("deploy/compose/prometheus.yml").read_text(encoding="utf-8")
    assert "metrics_path: /v1/observability/metrics" in content
    assert "metrics_path: /metrics" not in content


def test_readiness_alert_rules_file_exists() -> None:
    assert Path("deploy/compose/prometheus-alerts.yml").is_file()


def test_readiness_alert_rules_contract() -> None:
    content = Path("deploy/compose/prometheus-alerts.yml").read_text(encoding="utf-8")

    assert "alert: AjendaDatabaseReadinessUnavailable" in content
    assert "alert: AjendaQueueReadinessUnavailable" in content

    assert 'expr: ajenda_readiness_dependency_status{dependency="database"} == 0' in content
    assert 'expr: ajenda_readiness_dependency_status{dependency="queue"} == 0' in content

    assert "severity: critical" in content
    assert "for: 2m" in content

    assert "ajenda_readiness_dependency_status" in content
    assert 'dependency="database"' in content
    assert 'dependency="queue"' in content

    banned_substrings = (
        "/metrics",
        "/health",
        "/readiness",
        "http://",
        "https://",
        "tenant",
        "exception",
        "hostname",
    )
    for line in content.splitlines():
        if not line.strip().startswith("expr:"):
            continue
        for banned in banned_substrings:
            assert banned not in line


def test_compose_prometheus_loads_readiness_alert_rules() -> None:
    content = Path("deploy/compose/prometheus.yml").read_text(encoding="utf-8")
    assert "rule_files:" in content
    assert "- /etc/prometheus/alerts/prometheus-alerts.yml" in content
