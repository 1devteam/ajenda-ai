"""F3-B deployment/runtime configuration contract guards.

These tests intentionally stay static: they validate deployment strings,
environment-variable names, proof-script Compose invocation, and worker
entrypoint alignment without requiring Docker, Kubernetes, Terraform, or cloud
credentials.
"""

from __future__ import annotations

import re
from pathlib import Path

DEPLOYMENT_CONTRACT_PATHS = (
    Path("deploy/compose/.env.prod.example"),
    Path("deploy/compose/docker-compose.prod.yml"),
    Path("deploy/scripts/live-runtime-proof.sh"),
    Path(".github/workflows/live-runtime-proof.yml"),
    Path("deploy/k8s/configmap.yaml"),
    Path("deploy/k8s/secret.example.yaml"),
    Path("docs/deployment/production-env-contract.md"),
)

PRODUCTION_REQUIRED_APP_ENV = frozenset(
    {
        "AJENDA_DATABASE_URL",
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_AUTHZ_POLICY_MODE",
        "AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS",
    }
)

LIVE_PROOF_REQUIRED_APP_ENV = frozenset(
    {
        "AJENDA_DATABASE_URL",
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
    }
)

PRODUCTION_OPTIONAL_APP_ENV = frozenset(
    {
        "AJENDA_APP_NAME",
        "AJENDA_LOG_LEVEL",
        "AJENDA_LOG_JSON",
        "AJENDA_HOST",
        "AJENDA_PORT",
        "AJENDA_DB_POOL_SIZE",
        "AJENDA_DB_MAX_OVERFLOW",
        "AJENDA_DB_POOL_TIMEOUT",
        "AJENDA_DB_POOL_RECYCLE",
        "AJENDA_REDACT_KEYS",
        "AJENDA_WORKER_POLL_INTERVAL_SECONDS",
        "AJENDA_WORKER_IDENTITY",
        "AJENDA_RATE_LIMIT_REQUESTS",
        "AJENDA_RATE_LIMIT_WINDOW_SECONDS",
        "AJENDA_AUTHZ_OPA_URL",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
    }
)

NON_SETTINGS_DEPLOYMENT_ENV = frozenset(
    {
        "AJENDA_PROOF_API_BASE_URL",
        "AJENDA_PROOF_COMPOSE_ENV_FILE",
        "AJENDA_PROOF_COMPOSE_FILE",
        "AJENDA_PROOF_CURL_CONNECT_TIMEOUT_SECONDS",
        "AJENDA_PROOF_CURL_MAX_TIME_SECONDS",
        "AJENDA_PROOF_POLL_SECONDS",
        "AJENDA_PROOF_PROMETHEUS_BASE_URL",
        "AJENDA_PROOF_PROMETHEUS_JOB_NAME",
        "AJENDA_PROOF_TIMEOUT_SECONDS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "POSTGRES_PASSWORD",
        "PROMETHEUS_ENABLED",
        "PROMETHEUS_IMAGE",
    }
)

SECRET_ENV = frozenset(
    {
        "AJENDA_DATABASE_URL",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
        "POSTGRES_PASSWORD",
    }
)

VALID_WORKER_ENTRYPOINT_MARKERS = (
    'ENTRYPOINT ["/app/deploy/scripts/start-worker.sh"]',
    "from backend.workers.worker_loop import WorkerLoop",
    "WorkerLoop(",
)

STALE_WORKER_ENTRYPOINT_MARKERS = (
    "backend.worker",
    "task_worker",
    "runtime_worker",
    "python -m backend.worker",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _settings_env_aliases() -> set[str]:
    config_text = _read(Path("backend/app/config.py"))
    return set(re.findall(r'alias="(AJENDA_[A-Z0-9_]+)"', config_text))


def _env_names(text: str) -> set[str]:
    return set(re.findall(r"\b(?:AJENDA|POSTGRES|PROMETHEUS|OTEL)_[A-Z0-9_]+\b", text))


def _assignment_names(text: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE))


def _k8s_data_names(text: str) -> set[str]:
    return set(re.findall(r"^  ([A-Z][A-Z0-9_]+):", text, flags=re.MULTILINE))


def _deployment_text(paths: tuple[Path, ...] = DEPLOYMENT_CONTRACT_PATHS) -> str:
    return "\n".join(_read(path) for path in paths)


def test_config_exposes_only_canonical_ajenda_env_aliases() -> None:
    aliases = _settings_env_aliases()

    assert PRODUCTION_REQUIRED_APP_ENV <= aliases
    assert PRODUCTION_OPTIONAL_APP_ENV <= aliases
    assert "DATABASE_URL" not in aliases
    assert "QUEUE_URL" not in aliases
    assert "QUEUE_BACKEND" not in aliases


def test_production_env_template_uses_supported_settings_env_names() -> None:
    env_template = _read(Path("deploy/compose/.env.prod.example"))
    assigned_names = _assignment_names(env_template)
    supported = _settings_env_aliases() | NON_SETTINGS_DEPLOYMENT_ENV

    unsupported = assigned_names - supported
    missing_required = PRODUCTION_REQUIRED_APP_ENV - assigned_names

    assert not unsupported, f"Unsupported production env names: {sorted(unsupported)}"
    assert not missing_required, f"Missing required production env names: {sorted(missing_required)}"
    assert "POSTGRES_PASSWORD=CHANGE_ME_USE_STRONG_RANDOM_PASSWORD" in env_template
    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY=CHANGE_ME_GENERATE_WITH_FERNET" in env_template


def test_k8s_config_and_secret_partition_canonical_env_names() -> None:
    configmap = _read(Path("deploy/k8s/configmap.yaml"))
    secret = _read(Path("deploy/k8s/secret.example.yaml"))
    config_names = _k8s_data_names(configmap)
    secret_names = _k8s_data_names(secret)
    supported = _settings_env_aliases() | NON_SETTINGS_DEPLOYMENT_ENV

    assert not (config_names & SECRET_ENV), f"Secrets must not be in ConfigMap: {sorted(config_names & SECRET_ENV)}"
    assert SECRET_ENV <= secret_names
    assert PRODUCTION_REQUIRED_APP_ENV <= (config_names | secret_names)
    assert not ((config_names | secret_names) - supported)


def test_live_runtime_proof_workflow_writes_canonical_compose_env_file() -> None:
    workflow = _read(Path(".github/workflows/live-runtime-proof.yml"))
    names = _env_names(workflow)

    assert "AJENDA_PROOF_COMPOSE_ENV_FILE: deploy/compose/.env.prod" in workflow
    assert 'env_path = Path("deploy/compose/.env.prod")' in workflow
    assert LIVE_PROOF_REQUIRED_APP_ENV <= names
    assert "AJENDA_ENV=staging" in workflow
    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY" not in workflow
    assert not (names - _settings_env_aliases() - NON_SETTINGS_DEPLOYMENT_ENV)


def test_compose_and_live_proof_use_same_env_file_for_config_up_exec_down() -> None:
    compose = _read(Path("deploy/compose/docker-compose.prod.yml"))
    script = _read(Path("deploy/scripts/live-runtime-proof.sh"))
    workflow = _read(Path(".github/workflows/live-runtime-proof.yml"))

    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env.prod}" in compose
    assert "image: ${PROMETHEUS_IMAGE:-prom/prometheus:v2.54.1}" in compose
    assert 'COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"' in script
    assert 'docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"' in script
    assert "compose config --quiet" in script
    assert "compose up -d --build db redis migrate api worker prometheus otel-collector" in script
    assert (
        'docker compose --env-file "$AJENDA_PROOF_COMPOSE_ENV_FILE" -f deploy/compose/docker-compose.prod.yml down -v --remove-orphans'
        in workflow
    )


def test_worker_entrypoint_is_consistent_across_deployment_targets() -> None:
    worker_dockerfile = _read(Path("deploy/docker/worker.Dockerfile"))
    start_worker = _read(Path("deploy/scripts/start-worker.sh"))
    deployment_text = _deployment_text(
        (
            Path("deploy/compose/docker-compose.prod.yml"),
            Path("deploy/docker/worker.Dockerfile"),
            Path("deploy/scripts/start-worker.sh"),
            Path("deploy/k8s/worker-deployment.yaml"),
            Path("docs/deployment/production-env-contract.md"),
            Path(".github/workflows/live-runtime-proof.yml"),
        )
    )

    assert VALID_WORKER_ENTRYPOINT_MARKERS[0] in worker_dockerfile
    for marker in VALID_WORKER_ENTRYPOINT_MARKERS[1:]:
        assert marker in start_worker
    for stale_marker in STALE_WORKER_ENTRYPOINT_MARKERS:
        assert re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(stale_marker)}(?![A-Za-z0-9_.-])", deployment_text) is None


def test_health_readiness_and_metrics_paths_are_aligned() -> None:
    deployment_text = _deployment_text(
        (
            Path("deploy/compose/prometheus.yml"),
            Path("deploy/scripts/live-runtime-proof.sh"),
            Path("deploy/scripts/healthcheck.sh"),
            Path("deploy/scripts/readinesscheck.sh"),
            Path("deploy/k8s/api-deployment.yaml"),
            Path("deploy/k8s/prometheus-servicemonitor.yaml"),
        )
    )

    assert "/health" in deployment_text
    assert "/readiness" in deployment_text
    assert "/v1/system/health" in deployment_text
    assert "/v1/system/readiness" in deployment_text
    assert "/v1/observability/metrics" in deployment_text
    assert "/observability/metrics" not in deployment_text.replace("/v1/observability/metrics", "")


def test_terraform_or_ecs_contract_files_do_not_exist_without_deployment_tests() -> None:
    candidate_roots = [Path("deploy"), Path("infrastructure")]
    discovered: list[Path] = []
    for root in candidate_roots:
        if not root.exists():
            continue
        discovered.extend(path for path in root.rglob("*.tf") if path.is_file())
        discovered.extend(path for path in root.rglob("*ecs*") if path.is_file())
        discovered.extend(path for path in root.rglob("*task*definition*") if path.is_file())

    assert not discovered, (
        "Terraform/ECS deployment files need F3-B env/command/secret contract tests before being added: "
        f"{[str(path) for path in discovered]}"
    )
