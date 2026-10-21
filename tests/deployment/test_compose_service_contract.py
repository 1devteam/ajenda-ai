"""Drift guards for the prod-like Docker Compose service graph."""

from __future__ import annotations

import re
from pathlib import Path

COMPOSE_FILE = Path("deploy/compose/docker-compose.prod.yml")
LIVE_RUNTIME_PROOF = Path("deploy/scripts/live-runtime-proof.sh")
OPERATOR_MISSION_PROOF = Path("deploy/scripts/operator-mission-proof.py")
PLUGIN_RUNTIME_PROOF = Path("deploy/scripts/plugin-runtime-proof.sh")
STAGING_AUTONOMY_PLUGIN_PROOF = Path("deploy/scripts/staging-autonomy-plugin-proof.sh")

REQUIRED_SERVICES = frozenset(
    {
        "frontend",
        "api",
        "worker",
        "assurance",
        "role-bootstrap",
        "migrate",
        "db",
        "redis",
        "prometheus",
        "otel-collector",
    }
)

ENV_FILE_SERVICES = ("api", "worker", "assurance", "migrate")
LIVE_PROOF_STARTED_SERVICES = (
    "db",
    "redis",
    "migrate",
    "api",
    "worker",
    "assurance",
    "frontend",
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


def test_runtime_services_receive_only_their_own_database_identity() -> None:
    compose = _read(COMPOSE_FILE)
    expected = {
        "api": ("AJENDA_DATABASE_IDENTITY: api", "ajenda_api:${AJENDA_API_DATABASE_PASSWORD"),
        "worker": ("AJENDA_DATABASE_IDENTITY: worker", "ajenda_worker:${AJENDA_WORKER_DATABASE_PASSWORD"),
        "assurance": (
            "AJENDA_DATABASE_IDENTITY: assurance",
            "ajenda_assurance:${AJENDA_ASSURANCE_DATABASE_PASSWORD",
        ),
        "migrate": (
            "AJENDA_DATABASE_IDENTITY: migrator",
            "ajenda_migrator:${AJENDA_MIGRATOR_DATABASE_PASSWORD",
        ),
    }
    for service, fragments in expected.items():
        block = _service_block(compose, service)
        assert all(fragment in block for fragment in fragments)


def test_role_bootstrap_is_explicit_and_not_a_migration_dependency() -> None:
    compose = _read(COMPOSE_FILE)
    migration = _service_block(compose, "migrate")
    bootstrap = _service_block(compose, "role-bootstrap")

    assert "role-bootstrap:" not in migration
    assert 'profiles: ["bootstrap"]' in bootstrap
    assert "database_role_bootstrap.sql" in bootstrap
    assert "AJENDA_MIGRATOR_DATABASE_PASSWORD" in bootstrap


def test_api_service_waits_for_required_dependencies() -> None:
    api_block = _service_block(_read(COMPOSE_FILE), "api")

    assert "migrate:" in api_block
    assert "condition: service_completed_successfully" in api_block
    assert "db:" in api_block
    assert "condition: service_healthy" in api_block
    assert "redis:" in api_block
    assert "condition: service_started" in api_block
    assert "otel-collector:" in api_block
    assert "hubspot-crm-ingress:" not in api_block


def test_worker_service_waits_for_queue_database_and_migrations() -> None:
    worker_block = _service_block(_read(COMPOSE_FILE), "worker")

    assert "migrate:" in worker_block
    assert "condition: service_completed_successfully" in worker_block
    assert "db:" in worker_block
    assert "condition: service_healthy" in worker_block
    assert "redis:" in worker_block
    assert "condition: service_started" in worker_block
    assert "hubspot-crm-ingress:" not in worker_block


def test_worker_image_declares_browser_runtime_support() -> None:
    dockerfile = Path("deploy/docker/worker.Dockerfile").read_text(encoding="utf-8")
    startup = Path("deploy/scripts/start-worker.sh").read_text(encoding="utf-8")

    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "playwright install --with-deps chromium" in dockerfile
    assert "assert_browser_runtime_ready" in startup


def test_optional_hubspot_services_do_not_block_kernel_boot() -> None:
    compose = _read(COMPOSE_FILE)

    for service_name in ("hubspot-crm-adapter", "hubspot-crm-ingress"):
        assert 'profiles: ["hubspot"]' in _service_block(compose, service_name)


def test_live_runtime_proof_starts_core_proof_services() -> None:
    script = _read(LIVE_RUNTIME_PROOF)
    operator_script = _read(OPERATOR_MISSION_PROOF)

    expected_command = 'compose up -d "${proof_build_args[@]}" ' + " ".join(LIVE_PROOF_STARTED_SERVICES)

    assert 'COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"' in script
    assert 'FRONTEND_BASE_URL="${AJENDA_PROOF_FRONTEND_BASE_URL:-http://localhost:8080}"' in script
    assert 'if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then' in script
    assert 'fail "compose env file not found: $COMPOSE_ENV_FILE"' in script
    assert 'docker compose -p "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"' in script
    assert expected_command in script
    assert "compose down --remove-orphans" not in script
    assert "AJENDA_PROOF_START_SERVICES:-0" in script
    assert "AJENDA_PROOF_BOOTSTRAP_ROLES:-0" in script
    assert "AJENDA_PROOF_REBUILD:-0" in script
    assert 'if [[ "${AJENDA_PROOF_START_SERVICES:-0}" == "1" ]]; then' in script
    assert "AJENDA_PROOF_REBUILD=1 requires AJENDA_PROOF_START_SERVICES=1" in script
    assert "AJENDA_PROOF_BOOTSTRAP_ROLES=1 requires AJENDA_PROOF_START_SERVICES=1" in script
    assert "compose --profile bootstrap run --rm role-bootstrap" in script
    assert "operator-mission-proof.py" in script
    assert "AJENDA_OPERATOR_MISSION_PROOF" in script
    assert "AJENDA_OPERATOR_MISSION_PROOF" in script
    assert "operator mission proof is required" in script
    assert "graph_impact_analysis.py" in script
    assert "graph_runtime_impact.py" in script
    assert "AJENDA_PROOF_GRAFT_RUNTIME_IMPACT" in script
    assert "proof_status=0" in script
    assert "joined GRAFT artifact preserved" in script
    assert "ExecutionCoordinator" not in script
    assert "tool_invoke_handler" not in script
    assert "AJENDA_OPERATOR_PROOF_RUNTIME_EVIDENCE_OUTPUT" in script
    assert "AJENDA_OPERATOR_PROOF_RUNTIME_RECONCILIATION_OUTPUT" in operator_script
    assert 'wait_for_http_ok "$FRONTEND_BASE_URL/"' in script
    assert 'AJENDA_OPERATOR_PROOF_FRONTEND_BASE_URL="$FRONTEND_BASE_URL"' in script
    assert "AJENDA_OPERATOR_PROOF_CLIENT_IP" in operator_script
    assert 'request_headers["X-Forwarded-For"] = CLIENT_IP' in operator_script
    assert "mission reached terminal failure before deliverable" in operator_script
    assert "brain-capstone-runtime-proof.py" not in script
    assert "gtm.lead_enrich" not in script
    for phase in (
        "frontend_probe",
        "tenant_onboarding",
        "charter_persistence",
        "mission_composition",
        "mission_confirmation",
        "mission_launch",
        "mission_terminal_poll",
        "runtime_reconciliation",
        "cross_tenant_denial",
    ):
        assert f'log_phase("{phase}")' in operator_script


def test_operator_mission_proof_uses_public_api_and_never_direct_runtime_handlers() -> None:
    script = _read(OPERATOR_MISSION_PROOF)

    for path in (
        "/v1/onboarding/signup",
        "/v1/business-profile",
        "/v1/business-profile/facts/operating_charter",
        "/v1/missions/compose",
        "/v1/missions/proposals/",
        "/v1/missions/{mission_id}/launch",
        "/v1/missions/{mission_id}/deliverable",
        "/v1/missions/{mission_id}/runtime-reconciliation-export",
    ):
        assert path in script
    assert '"verification_code"' in script
    assert "mission did not complete acceptance" in script
    assert "persist_proof_operating_charter" in script
    assert "proof operating charter was not persisted as active revision one" in script
    assert '"tenant_id", "signup"' not in script
    assert "tool_invoke_handler" not in script
    assert "ExecutionCoordinator" not in script
    assert "sqlalchemy" not in script


def test_plugin_runtime_proof_script_is_env_gated() -> None:
    script = _read(PLUGIN_RUNTIME_PROOF)

    assert "AJENDA_PROOF_PLUGIN_LANE_ENABLED" in script
    assert "crm.research" in script
    assert "gtm.email_check" in script
    assert "autonomy_disclaimer_accepted" in script
    assert "provider-credentials" in script


def test_staging_autonomy_plugin_proof_delegates_to_plugin_lane() -> None:
    script = _read(STAGING_AUTONOMY_PLUGIN_PROOF)

    assert "plugin-runtime-proof.sh" in script
    assert "AJENDA_PROOF_AUTONOMY_LANE" in script


def test_compose_exposes_expected_loopback_runtime_ports() -> None:
    compose = _read(COMPOSE_FILE)

    assert '"127.0.0.1:8000:8000"' in _service_block(compose, "api")
    assert '"127.0.0.1:9090:9090"' in _service_block(compose, "prometheus")
    assert '"127.0.0.1:4317:4317"' in _service_block(compose, "otel-collector")


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


def test_database_healthcheck_is_independent_of_runtime_role_provisioning() -> None:
    for path in (COMPOSE_FILE, Path("docker-compose.yml")):
        database_block = _service_block(_read(path), "db")
        assert "pg_isready -d ajenda" in database_block
        assert "pg_isready -U" not in database_block


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


def test_prod_compose_only_publishes_loopback_ports() -> None:
    compose = _read(COMPOSE_FILE)
    for service, port in {
        "frontend": "8080:80",
        "api": "8000:8000",
        "prometheus": "9090:9090",
        "otel-collector": "4317:4317",
    }.items():
        block = _service_block(compose, service)
        assert f'"127.0.0.1:{port}"' in block
        assert f'      - "{port}"' not in block


def test_local_compose_only_publishes_loopback_ports() -> None:
    compose = _read(Path("docker-compose.yml"))
    for service, port in {
        "frontend": "8080:80",
        "api": "8000:8000",
        "db": "5432:5432",
        "redis": "6379:6379",
        "hubspot-crm-adapter": "8088:8080",
        "hubspot-crm-ingress": "8443:443",
    }.items():
        block = _service_block(compose, service)
        assert f'"127.0.0.1:{port}"' in block
        assert f'      - "{port}"' not in block
