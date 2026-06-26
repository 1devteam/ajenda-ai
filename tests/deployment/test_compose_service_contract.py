"""Drift guards for the prod-like Docker Compose service graph."""

from __future__ import annotations

import re
from pathlib import Path

COMPOSE_FILE = Path("deploy/compose/docker-compose.prod.yml")
LIVE_RUNTIME_PROOF = Path("deploy/scripts/live-runtime-proof.sh")
PLUGIN_RUNTIME_PROOF = Path("deploy/scripts/plugin-runtime-proof.sh")
STAGING_AUTONOMY_PLUGIN_PROOF = Path("deploy/scripts/staging-autonomy-plugin-proof.sh")

REQUIRED_SERVICES = frozenset(
    {
        "api",
        "worker",
        "migrate",
        "db",
        "redis",
        "prometheus",
        "otel-collector",
    }
)

ENV_FILE_SERVICES = ("api", "worker", "migrate")
LIVE_PROOF_STARTED_SERVICES = (
    "db",
    "redis",
    "migrate",
    "api",
    "worker",
    "prometheus",
    "otel-collector",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service_names(compose_text: str) -> set[str]:
    return set(re.findall(r"^  ([a-z][a-z0-9-]*):$", compose_text, flags=re.MULTILINE))


def _service_block(compose_text: str, service_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(service_name)}:\n(?P<body>(?:^    .+\n|^\s*$)+)",
        compose_text,
        flags=re.MULTILINE,
    )
    assert match is not None, f"missing compose service block: {service_name}"
    return match.group("body")


def test_prod_compose_declares_required_runtime_services() -> None:
    compose = _read(COMPOSE_FILE)

    missing = REQUIRED_SERVICES - _service_names(compose)

    assert not missing, f"Missing required services from {COMPOSE_FILE}: {sorted(missing)}"


def test_runtime_services_load_prod_env_file() -> None:
    compose = _read(COMPOSE_FILE)

    for service_name in ENV_FILE_SERVICES:
        block = _service_block(compose, service_name)
        assert "env_file:" in block
        assert "- .env.prod" in block


def test_api_service_waits_for_required_dependencies() -> None:
    api_block = _service_block(_read(COMPOSE_FILE), "api")

    assert "migrate:" in api_block
    assert "condition: service_completed_successfully" in api_block
    assert "db:" in api_block
    assert "condition: service_healthy" in api_block
    assert "redis:" in api_block
    assert "condition: service_started" in api_block
    assert "otel-collector:" in api_block


def test_worker_service_waits_for_queue_database_and_migrations() -> None:
    worker_block = _service_block(_read(COMPOSE_FILE), "worker")

    assert "migrate:" in worker_block
    assert "condition: service_completed_successfully" in worker_block
    assert "db:" in worker_block
    assert "condition: service_healthy" in worker_block
    assert "redis:" in worker_block
    assert "condition: service_started" in worker_block


def test_live_runtime_proof_starts_core_proof_services() -> None:
    script = _read(LIVE_RUNTIME_PROOF)

    expected_command = "compose up -d --build " + " ".join(LIVE_PROOF_STARTED_SERVICES)

    assert 'COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"' in script
    assert 'if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then' in script
    assert 'fail "compose env file not found: $COMPOSE_ENV_FILE"' in script
    assert 'docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"' in script
    assert expected_command in script
    assert 'log "queueing low-risk GTM lead enrich proof task"' in script
    assert '"action": "gtm.lead_enrich"' in script
    assert 'AJENDA_PROOF_PLUGIN_LANE_ENABLED' in script
    assert "plugin-runtime-proof.sh" in script


def test_plugin_runtime_proof_script_is_env_gated() -> None:
    script = _read(PLUGIN_RUNTIME_PROOF)

    assert 'AJENDA_PROOF_PLUGIN_LANE_ENABLED' in script
    assert "crm.research" in script
    assert "gtm.email_check" in script
    assert "autonomy_disclaimer_accepted" in script
    assert "provider-credentials" in script


def test_staging_autonomy_plugin_proof_delegates_to_plugin_lane() -> None:
    script = _read(STAGING_AUTONOMY_PLUGIN_PROOF)

    assert "plugin-runtime-proof.sh" in script
    assert "AJENDA_PROOF_AUTONOMY_LANE" in script


def test_compose_exposes_expected_runtime_ports() -> None:
    compose = _read(COMPOSE_FILE)

    assert '"8000:8000"' in _service_block(compose, "api")
    assert '"9090:9090"' in _service_block(compose, "prometheus")
    assert '"4317:4317"' in _service_block(compose, "otel-collector")


def test_compose_mounts_prometheus_and_otel_config() -> None:
    compose = _read(COMPOSE_FILE)

    assert "./prometheus.yml:/etc/prometheus/prometheus.yml:ro" in _service_block(
        compose,
        "prometheus",
    )
    assert "../k8s/otel-collector-config.yaml:/etc/otelcol/config.yaml:ro" in _service_block(
        compose,
        "otel-collector",
    )


def test_compose_api_healthcheck_uses_readiness_endpoint() -> None:
    api_block = _service_block(_read(COMPOSE_FILE), "api")
    assert "/app/deploy/scripts/readinesscheck.sh" in api_block
    assert "/app/deploy/scripts/healthcheck.sh" not in api_block


def test_live_runtime_proof_initializes_readiness_before_metrics_scrape() -> None:
    script = _read(LIVE_RUNTIME_PROOF)

    readiness_index = script.index('wait_for_http_ok "$API_BASE_URL/readiness"')
    metrics_index = script.index('metrics_body="$(curl_body "$API_BASE_URL/v1/observability/metrics")"')

    assert readiness_index < metrics_index


def test_live_runtime_proof_validates_prometheus_rule_file_and_metrics_path_contract() -> None:
    script = _read(LIVE_RUNTIME_PROOF)

    assert 'wait_for_http_ok "$PROMETHEUS_BASE_URL/-/ready"' in script
    assert 'wait_for_prometheus_target_up "$PROMETHEUS_JOB_NAME"' in script
    assert 'curl_body "$API_BASE_URL/v1/observability/metrics"' in script
