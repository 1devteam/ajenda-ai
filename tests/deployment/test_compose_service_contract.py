"""Drift guards for the prod-like Docker Compose service graph."""

from __future__ import annotations

import re
from pathlib import Path

COMPOSE_FILE = Path("deploy/compose/docker-compose.prod.yml")
LIVE_RUNTIME_PROOF = Path("deploy/scripts/live-runtime-proof.sh")

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
