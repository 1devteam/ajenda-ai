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

DATABASE_ROLE_DEPLOYMENT_ENV = frozenset(
    {
        "AJENDA_DATABASE_BOOTSTRAP_URL",
        "AJENDA_API_DATABASE_PASSWORD",
        "AJENDA_WORKER_DATABASE_PASSWORD",
        "AJENDA_ASSURANCE_DATABASE_PASSWORD",
        "AJENDA_MIGRATOR_DATABASE_PASSWORD",
        "AJENDA_API_DATABASE_URL",
        "AJENDA_WORKER_DATABASE_URL",
        "AJENDA_ASSURANCE_DATABASE_URL",
        "AJENDA_MIGRATOR_DATABASE_URL",
    }
)

PRODUCTION_REQUIRED_APP_ENV = frozenset(
    {
        "AJENDA_API_DATABASE_PASSWORD",
        "AJENDA_WORKER_DATABASE_PASSWORD",
        "AJENDA_ASSURANCE_DATABASE_PASSWORD",
        "AJENDA_MIGRATOR_DATABASE_PASSWORD",
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_MODE",
        "AJENDA_WORKER_TENANT_REFRESH_SECONDS",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
        "AJENDA_AUTHZ_POLICY_MODE",
        "AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS",
        "AJENDA_EMAIL_PROVIDER",
        "AJENDA_EMAIL_FROM",
        "AJENDA_SIGNUP_VERIFY_URL_BASE",
        "AJENDA_CORS_ALLOWED_ORIGINS",
        "AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STARTER",
        "STRIPE_PRICE_PRO",
    }
)

LIVE_PROOF_REQUIRED_APP_ENV = frozenset(
    {
        "AJENDA_API_DATABASE_PASSWORD",
        "AJENDA_WORKER_DATABASE_PASSWORD",
        "AJENDA_ASSURANCE_DATABASE_PASSWORD",
        "AJENDA_MIGRATOR_DATABASE_PASSWORD",
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
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
        "AJENDA_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS",
        "AJENDA_UVICORN_WORKERS",
        "AJENDA_REDACT_KEYS",
        "AJENDA_WORKER_POLL_INTERVAL_SECONDS",
        "AJENDA_WORKER_IDENTITY",
        "AJENDA_RATE_LIMIT_REQUESTS",
        "AJENDA_RATE_LIMIT_WINDOW_SECONDS",
        "AJENDA_AUTHZ_OPA_URL",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
    }
)

LEGACY_UNSUPPORTED_APP_ENV = frozenset(
    {
        "DATABASE_URL",
        "QUEUE_URL",
        "QUEUE_BACKEND",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
    }
)

NON_SETTINGS_DEPLOYMENT_ENV = frozenset(
    {
        "AJENDA_OPERATOR_MISSION_PROOF",
        *DATABASE_ROLE_DEPLOYMENT_ENV,
        "AJENDA_OPERATOR_PROOF_EXPECTED_PROSPECT_COUNT",
        "AJENDA_OPERATOR_PROOF_INSTRUCTION",
        "AJENDA_PROOF_API_BASE_URL",
        "AJENDA_PROOF_BOOTSTRAP_ROLES",
        "AJENDA_PROOF_COMPOSE_ENV_FILE",
        "AJENDA_PROOF_COMPOSE_API_HOST_PORT",
        "AJENDA_PROOF_COMPOSE_FRONTEND_HOST_PORT",
        "AJENDA_PROOF_COMPOSE_PROMETHEUS_HOST_PORT",
        "AJENDA_PROOF_COMPOSE_OTEL_HOST_PORT",
        "AJENDA_PROOF_COMPOSE_FILE",
        "AJENDA_PROOF_COMPOSE_PROJECT_NAME",
        "AJENDA_PROOF_CURL_CONNECT_TIMEOUT_SECONDS",
        "AJENDA_PROOF_CURL_MAX_TIME_SECONDS",
        "AJENDA_PROOF_POLL_SECONDS",
        "AJENDA_PROOF_PROMETHEUS_BASE_URL",
        "AJENDA_PROOF_PROMETHEUS_JOB_NAME",
        "AJENDA_PROOF_START_SERVICES",
        "AJENDA_PROOF_TIMEOUT_SECONDS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "POSTGRES_PASSWORD",
        "PROMETHEUS_ENABLED",
        "PROMETHEUS_IMAGE",
    }
)

SECRET_ENV = frozenset(
    {
        "AJENDA_API_DATABASE_URL",
        "AJENDA_WORKER_DATABASE_URL",
        "AJENDA_ASSURANCE_DATABASE_URL",
        "AJENDA_MIGRATOR_DATABASE_URL",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
        "POSTGRES_PASSWORD",
        # Billing — Stripe credentials must live in the Secret, never in ConfigMap
        "STRIPE_SECRET_KEY",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STARTER",
        "STRIPE_PRICE_PRO",
        "AJENDA_RESEND_API_KEY",
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
    # Capture all canonical env aliases regardless of prefix (AJENDA_, STRIPE_, etc.)
    return set(re.findall(r'alias="([A-Z][A-Z0-9_]+)"', config_text))


def _env_names(text: str) -> set[str]:
    prefixed_names = set(re.findall(r"\b(?:AJENDA|POSTGRES|PROMETHEUS|OTEL)_[A-Z0-9_]+\b", text))
    assigned_names = set(re.findall(r"\b([A-Z][A-Z0-9_]+)\s*(?==|:)", text))
    return prefixed_names | (assigned_names & LEGACY_UNSUPPORTED_APP_ENV)


def _assignment_names(text: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE))


def _k8s_data_names(text: str) -> set[str]:
    return set(re.findall(r"^  ([A-Z][A-Z0-9_]+):", text, flags=re.MULTILINE))


def _deployment_text(paths: tuple[Path, ...] = DEPLOYMENT_CONTRACT_PATHS) -> str:
    return "\n".join(_read(path) for path in paths)


def test_config_exposes_only_canonical_ajenda_env_aliases() -> None:
    aliases = _settings_env_aliases()

    assert (PRODUCTION_REQUIRED_APP_ENV - DATABASE_ROLE_DEPLOYMENT_ENV) <= aliases
    assert PRODUCTION_OPTIONAL_APP_ENV <= aliases
    assert "DATABASE_URL" not in aliases
    assert "QUEUE_URL" not in aliases
    assert "QUEUE_BACKEND" not in aliases


def test_workflow_env_extraction_catches_legacy_unprefixed_app_aliases() -> None:
    workflow_fragment = """
    env:
      DATABASE_URL: postgresql://example
    run: |
      QUEUE_URL=redis://redis:6379/0
      AJENDA_ENV=production
      POSTGRES_PASSWORD=example
    """

    assert _env_names(workflow_fragment) >= {
        "AJENDA_ENV",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "QUEUE_URL",
    }


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
    assert "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY=CHANGE_ME_GENERATE_WITH_FERNET" in env_template


def test_k8s_config_and_secret_partition_canonical_env_names() -> None:
    configmap = _read(Path("deploy/k8s/configmap.yaml"))
    secret = _read(Path("deploy/k8s/secret.example.yaml"))
    config_names = _k8s_data_names(configmap)
    secret_names = _k8s_data_names(secret)
    supported = _settings_env_aliases() | NON_SETTINGS_DEPLOYMENT_ENV
    k8s_required = PRODUCTION_REQUIRED_APP_ENV - {
        "AJENDA_API_DATABASE_PASSWORD",
        "AJENDA_WORKER_DATABASE_PASSWORD",
        "AJENDA_ASSURANCE_DATABASE_PASSWORD",
        "AJENDA_MIGRATOR_DATABASE_PASSWORD",
    } | {
        "AJENDA_API_DATABASE_URL",
        "AJENDA_WORKER_DATABASE_URL",
        "AJENDA_ASSURANCE_DATABASE_URL",
        "AJENDA_MIGRATOR_DATABASE_URL",
    }

    assert not (config_names & SECRET_ENV), f"Secrets must not be in ConfigMap: {sorted(config_names & SECRET_ENV)}"
    assert SECRET_ENV <= secret_names
    assert k8s_required <= (config_names | secret_names)
    assert not ((config_names | secret_names) - supported)


def test_live_runtime_proof_workflow_writes_canonical_compose_env_file() -> None:
    workflow = _read(Path(".github/workflows/live-runtime-proof.yml"))
    names = _env_names(workflow)

    assert "AJENDA_PROOF_COMPOSE_ENV_FILE: deploy/compose/.env.prod" in workflow
    assert 'env_path = Path("deploy/compose/.env.prod")' in workflow
    assert LIVE_PROOF_REQUIRED_APP_ENV <= names
    assert "AJENDA_ENV=staging" in workflow
    assert '"AJENDA_WORKER_TENANT_MODE=multi"' in workflow
    assert 'AJENDA_PROOF_START_SERVICES: "1"' in workflow
    assert 'AJENDA_PROOF_BOOTSTRAP_ROLES: "1"' in workflow
    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY" not in workflow
    assert not (names - _settings_env_aliases() - NON_SETTINGS_DEPLOYMENT_ENV)
    for workflow_path in (
        Path(".github/workflows/live-runtime-proof.yml"),
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/premerge-live-runtime-proof.yml"),
    ):
        workflow_text = _read(workflow_path)
        assert '"AJENDA_WORKER_TENANT_MODE=multi"' in workflow_text
        assert 'AJENDA_PROOF_START_SERVICES: "1"' in workflow_text
        assert 'AJENDA_PROOF_BOOTSTRAP_ROLES: "1"' in workflow_text

    premerge_workflow = _read(Path(".github/workflows/premerge-live-runtime-proof.yml"))
    premerge_names = _env_names(premerge_workflow)
    assert LIVE_PROOF_REQUIRED_APP_ENV <= premerge_names
    assert premerge_workflow.count('AJENDA_PROOF_START_SERVICES: "1"') == 1
    assert "from base64 import urlsafe_b64encode" in premerge_workflow
    assert "from secrets import token_bytes" in premerge_workflow
    assert 'runtime_fernet_key = urlsafe_b64encode(token_bytes(32)).decode("ascii")' in premerge_workflow
    assert 'print(f"::add-mask::{runtime_fernet_key}")' in premerge_workflow


def test_compose_and_live_proof_use_same_env_file_for_config_up_exec_down() -> None:
    compose = _read(Path("deploy/compose/docker-compose.prod.yml"))
    script = _read(Path("deploy/scripts/live-runtime-proof.sh"))
    workflow = _read(Path(".github/workflows/live-runtime-proof.yml"))

    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env.prod}" in compose
    assert "image: ${PROMETHEUS_IMAGE:-prom/prometheus:v2.54.1}" in compose
    assert 'COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"' in script
    assert 'AJENDA_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE"' in script
    assert 'AJENDA_COMPOSE_API_HOST_PORT="$COMPOSE_API_HOST_PORT"' in script
    assert 'AJENDA_COMPOSE_FRONTEND_HOST_PORT="$COMPOSE_FRONTEND_HOST_PORT"' in script
    assert 'AJENDA_COMPOSE_PROMETHEUS_HOST_PORT="$COMPOSE_PROMETHEUS_HOST_PORT"' in script
    assert 'AJENDA_COMPOSE_OTEL_HOST_PORT="$COMPOSE_OTEL_HOST_PORT"' in script
    assert 'docker compose -p "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"' in script
    assert "compose config --quiet" in script
    assert (
        'COMPOSE_ENV_FILE="$(cd "$(dirname "$COMPOSE_ENV_FILE")" && pwd -P)/$(basename "$COMPOSE_ENV_FILE")"' in script
    )
    assert 'COMPOSE_FRONTEND_HOST_PORT="${AJENDA_PROOF_COMPOSE_FRONTEND_HOST_PORT:-8080}"' in script
    assert (
        'FRONTEND_BASE_URL="${AJENDA_PROOF_FRONTEND_BASE_URL:-http://localhost:${COMPOSE_FRONTEND_HOST_PORT}}"'
        in script
    )
    assert 'wait_for_http_ok "$FRONTEND_BASE_URL/"' in script
    assert "AJENDA_PROOF_START_SERVICES:-0" in script
    assert "AJENDA_PROOF_BOOTSTRAP_ROLES:-0" in script
    assert "AJENDA_PROOF_REBUILD:-0" in script
    assert "compose --profile bootstrap run --rm role-bootstrap" in script
    assert "AJENDA_PROOF_BOOTSTRAP_ROLES=1 requires AJENDA_PROOF_START_SERVICES=1" in script
    assert "proof_build_args+=(--build)" in script
    assert (
        'compose up -d "${proof_build_args[@]}" db redis migrate api worker assurance frontend prometheus otel-collector'
        in script
    )
    assert "compose down --remove-orphans" not in script
    assert (
        'docker compose -p "$AJENDA_PROOF_COMPOSE_PROJECT_NAME" --env-file "$AJENDA_PROOF_COMPOSE_ENV_FILE" -f deploy/compose/docker-compose.prod.yml down --remove-orphans'
        in workflow
    )
    main_workflow = _read(Path(".github/workflows/ci.yml"))
    assert "Capture compose diagnostics" in main_workflow
    assert "main-live-runtime-proof-diagnostics" in main_workflow
    assert "logs --no-color --tail=300 > artifacts/live-runtime-proof/compose-logs.txt" in main_workflow


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


def test_terraform_ecs_owner_is_covered_by_this_contract_module() -> None:
    """Prevent the old `infrastructure/`-only scan from hiding `infra/`."""

    terraform_files = sorted(Path("infra").rglob("*.tf"))
    assert terraform_files, "infra/ is a declared deployment owner and must remain covered below"


def test_ecs_terraform_uses_the_current_role_specific_runtime_contract() -> None:
    """Keep the declared AWS target aligned with the proven Compose/runtime spine.

    This is intentionally a source-level guard. It does not claim an AWS deployment
    has occurred; an authorized target-environment proof remains separately required.
    """

    ecs = _read(Path("infra/modules/ecs/main.tf"))
    frontend = _read(Path("infra/modules/ecs/frontend.tf"))
    variables = _read(Path("infra/modules/ecs/variables.tf"))
    staging = _read(Path("infra/environments/staging/main.tf"))
    production = _read(Path("infra/environments/production/main.tf"))

    for stale_name in LEGACY_UNSUPPORTED_APP_ENV | {"APP_ENV", "LOG_LEVEL", "WORKER_MODE"}:
        assert f'name = "{stale_name}"' not in ecs
    for stale_marker in STALE_WORKER_ENTRYPOINT_MARKERS:
        assert stale_marker not in ecs

    for role in ("api", "worker", "assurance", "migrator"):
        assert f'aws_ecs_task_definition" "{role}"' in ecs
        assert f"var.{role}_image" in ecs
        assert f'aws_cloudwatch_log_group" "{role}"' in ecs
        assert f'variable "{role}_image"' in variables
        assert f"{role}_image" in staging
        assert f"{role}_image" in production

    assert "AJENDA_DATABASE_IDENTITY" in ecs
    assert "AJENDA_DATABASE_URL" in ecs
    assert "AJENDA_QUEUE_URL" in variables
    assert 'aws_ecs_service" "assurance"' in ecs
    assert 'aws_ecs_task_definition" "migrator"' in ecs
    assert ecs.count("desired_count   = 0") == 3
    assert "min_capacity       = 0" in ecs
    assert 'for_each = toset(["api", "worker", "assurance", "migrator", "frontend"])' in ecs
    assert "for_each   = var.secrets_read_policy_arns" in ecs
    for role in ("api", "worker", "assurance", "migrator"):
        assert f'aws_iam_role.ecs_execution["{role}"].arn' in ecs
    assert "image" in frontend and "var.frontend_image" in frontend
    assert 'aws_iam_role.ecs_execution["frontend"].arn' in frontend
    assert "image_tag" not in (ecs + frontend + variables + staging + production)

    for environment in ("staging", "production"):
        outputs = _read(Path(f"infra/environments/{environment}/outputs.tf"))
        for promotion_output in (
            "api_service_name",
            "worker_service_name",
            "assurance_service_name",
            "migrator_task_definition_arn",
            "api_task_definition_arn",
            "worker_task_definition_arn",
            "assurance_task_definition_arn",
        ):
            assert f'output "{promotion_output}"' in outputs


def test_terraform_accepts_secret_references_not_secret_values() -> None:
    secrets = _read(Path("infra/modules/secrets/main.tf"))
    staging_variables = _read(Path("infra/environments/staging/variables.tf"))
    production_variables = _read(Path("infra/environments/production/variables.tf"))
    staging = _read(Path("infra/environments/staging/main.tf"))
    production = _read(Path("infra/environments/production/main.tf"))

    assert "aws_secretsmanager_secret_version" not in secrets
    assert "secret_string" not in secrets
    for legacy_secret_input in (
        'variable "db_password"',
        'variable "redis_auth_token"',
        'variable "oidc_signing_key_pem"',
        'variable "webhook_hmac_master_key"',
    ):
        assert legacy_secret_input not in (staging_variables + production_variables)
    for legacy_reference in (
        "db_password             = var.db_password",
        "redis_auth_token        = var.redis_auth_token",
        "oidc_signing_key_pem    = var.oidc_signing_key_pem",
        "webhook_hmac_master_key = var.webhook_hmac_master_key",
    ):
        assert legacy_reference not in (staging + production)


def test_ecs_promotion_and_rollback_are_explicit_schema_aware_operator_steps() -> None:
    promotion = _read(Path("deploy/scripts/ecs-promote.sh"))
    rollback = _read(Path("deploy/scripts/ecs-rollback.sh"))

    assert "AJENDA_ECS_PROMOTION_APPROVED" in promotion
    assert "aws ecs run-task" in promotion
    assert "aws ecs wait tasks-stopped" in promotion
    assert "AJENDA_ECS_MIGRATOR_TASK_DEFINITION" in promotion
    assert "AJENDA_ECS_API_TASK_DEFINITION" in promotion
    assert "AJENDA_ECS_WORKER_TASK_DEFINITION" in promotion
    assert "AJENDA_ECS_ASSURANCE_TASK_DEFINITION" in promotion
    assert "AJENDA_ECS_API_DESIRED_COUNT" in promotion
    assert "application-autoscaling register-scalable-target" in promotion
    assert "terraform apply" not in promotion
    assert "provision-database-roles.sh" not in promotion

    assert "AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED" in rollback
    assert "Schema compatibility approval is required" in rollback
    assert "aws ecs update-service" in rollback
    assert "alembic" not in rollback


def test_cloud_target_docs_do_not_claim_unconfigured_redis_auth_or_secret_creation() -> None:
    infra_readme = _read(Path("infra/README.md"))
    production_contract = _read(Path("docs/deployment/production-env-contract.md"))

    assert "Redis auth token" not in infra_readme
    assert "Terraform creates neither the secret values nor the database" in production_contract
    assert "Authorized ECS staging proof remains required" in production_contract
