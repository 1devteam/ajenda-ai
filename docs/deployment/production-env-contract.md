# Production Environment Contract

Ajenda AI production deployments must not rely on development defaults.

## Required production values

| Variable | Required | Secret | Purpose |
|---|---:|---:|---|
| `POSTGRES_PASSWORD` | yes | yes | Database password. |
| `AJENDA_DATABASE_URL` | yes | yes | SQLAlchemy database URL. |
| `AJENDA_ENV=production` | yes | no | Enables production runtime validation. |
| `AJENDA_QUEUE_ADAPTER=redis` | yes | no | Production queue backend. |
| `AJENDA_QUEUE_URL` | yes | maybe | Redis URL. Secret if it includes a password. |
| `AJENDA_WORKER_TENANT_ID` | yes | no | Tenant queue processed by this worker group. |
| `AJENDA_OIDC_ISSUER` | yes | no | OIDC issuer. Must not be localhost in production. |
| `AJENDA_OIDC_JWKS_URI` | yes | no | OIDC JWKS endpoint. Must not be localhost in production. |
| `AJENDA_OIDC_AUDIENCE` | yes | no | Expected JWT audience. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY` | yes | yes | Fernet key for webhook signing-secret encryption. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV` | no | yes | Previous Fernet key during key-rotation migration windows. |
| `AJENDA_AUTHZ_POLICY_MODE` | yes | no | rbac, shadow_opa, or enforce_opa. |
| `AJENDA_AUTHZ_OPA_URL` | conditional | no | Required when policy mode is shadow_opa or enforce_opa. |
| `AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS` | yes | no | OPA request timeout. |
| `AJENDA_BUDGET_POLICY_ENABLED` | yes | no | Enables budget-policy scaffolding. |
| `AJENDA_BUDGET_POLICY_OBSERVE_ONLY` | yes | no | Observe-only mode for budget policy (Bundle 5.2 default). |
| `AJENDA_BUDGET_POLICY_ENFORCE` | yes | no | Must remain false for Bundle 5.2. |

## Generate webhook encryption key

Run:

python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

Store this value in a secrets manager and expose it as:

AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY

Do not use the deterministic development/test key in production.

## Worker tenant assignment

The current worker model is tenant-specific. AJENDA_WORKER_TENANT_ID must match the tenant queue this worker group is expected to process.

For multi-tenant production, use one of these patterns:

1. one worker deployment per tenant,
2. tenant-sharded worker pools,
3. future tenant-scanning worker scheduler.

Do not leave the worker tenant as default in production.

## Production startup guardrails

Settings.validate_runtime_contract() rejects production deployments that use:

- local queue adapter,
- Redis adapter without AJENDA_QUEUE_URL,
- localhost OIDC issuer/JWKS,
- missing or invalid webhook secret encryption key,
- deterministic development/test webhook key,
- default or blank worker tenant id,
- invalid rate-limit settings,
- OPA modes without OPA URL,
- budget enforcement without budget policy enablement,
- budget enforcement with observe-only still enabled.

## F3-B deployment/runtime source of truth

`backend/app/config.py` is the application settings source of truth. Production deployment surfaces must use the `AJENDA_*` aliases declared by `Settings` and must not use legacy unprefixed aliases such as `DATABASE_URL`, `QUEUE_URL`, `QUEUE_BACKEND`, `DB_HOST`, or `REDIS_HOST` for application configuration.

Non-application deployment variables are limited to deployment tooling or platform components:

- `POSTGRES_PASSWORD` for the PostgreSQL container and Compose interpolation.
- `PROMETHEUS_IMAGE` for deterministic-but-overridable Compose Prometheus image pinning.
- `OTEL_EXPORTER_OTLP_ENDPOINT` for OpenTelemetry exporter configuration.
- `PROMETHEUS_ENABLED` for deployment-level metrics enablement.
- `AJENDA_PROOF_*` variables for the live-runtime-proof harness only.

## Deployment target contract

| Target | Env contract | Runtime command contract | Probe / metrics contract |
|---|---|---|---|
| Docker Compose prod | `deploy/compose/docker-compose.prod.yml` loads `deploy/compose/.env.prod` for `api`, `worker`, and `migrate`; `.env.prod.example` documents required values. | API uses `deploy/scripts/start-api.sh`; worker uses `deploy/scripts/start-worker.sh`; migrations use `deploy/scripts/run-migrations.sh`. | API healthcheck uses `/health`; Prometheus scrapes `/v1/observability/metrics`. |
| Live runtime proof | `.github/workflows/live-runtime-proof.yml` writes `deploy/compose/.env.prod`; `deploy/scripts/live-runtime-proof.sh` runs Compose with `--env-file "$COMPOSE_ENV_FILE"` for `config`, `up`, `exec`, and related commands. | Starts `db redis migrate api worker prometheus otel-collector` and verifies worker completion through the supported worker image entrypoint. | Verifies `/health`, `/readiness`, `/v1/system/health`, `/v1/system/readiness`, Prometheus target health, live metrics, and Redis lease cleanup. |
| Kubernetes | `deploy/k8s/configmap.yaml` contains non-secret `AJENDA_*` values; `deploy/k8s/secret.example.yaml` contains secret placeholders for database URL, database password, and webhook encryption keys. | API, worker, and migration workloads rely on their image entrypoints. Worker images must use `deploy/scripts/start-worker.sh`, which starts `backend.workers.worker_loop.WorkerLoop`. | API probes use `/health` and `/readiness`; worker probes use `/tmp/worker-alive`; ServiceMonitor uses `/v1/observability/metrics`. |
| Terraform/ECS | No Terraform/ECS deployment files are present in this repository snapshot. | Not present. Add F3-B static env/command/secret tests before adding ECS task definitions. | Not present. |

## Worker runtime entrypoint

The supported deployment worker entrypoint is the worker image entrypoint:

```text
/app/deploy/scripts/start-worker.sh
```

That script validates settings, builds and pings the configured queue adapter, initializes `DatabaseRuntime`, and starts `backend.workers.worker_loop.WorkerLoop`. Deployment targets must not reference removed or stale worker module names from older top-level, task-specific, or runtime-specific worker entrypoints.
