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
| `AJENDA_WORKER_TENANT_MODE` | yes | no | `single` (one tenant) or `multi` (round-robin active tenants). |
| `AJENDA_WORKER_TENANT_REFRESH_SECONDS` | yes | no | Active-tenant roster refresh interval when mode is `multi`. |
| `AJENDA_WORKER_TENANT_ID` | conditional | no | Required when mode is `single`; ignored in `multi`. |
| `AJENDA_OIDC_ISSUER` | yes | no | OIDC issuer. Must not be localhost in production. |
| `AJENDA_OIDC_JWKS_URI` | yes | no | OIDC JWKS endpoint. Must not be localhost in production. |
| `AJENDA_OIDC_AUDIENCE` | yes | no | Expected JWT audience. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY` | yes | yes | Fernet key for webhook signing-secret encryption. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV` | no | yes | Previous Fernet key during webhook key-rotation migration windows. |
| `AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY` | yes | yes | Fernet key for provider runtime credential encryption. |
| `AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV` | no | yes | Previous Fernet key during provider credential key-rotation migration windows. |
| `AJENDA_AUTHZ_POLICY_MODE` | yes | no | rbac, shadow_opa, or enforce_opa. |
| `AJENDA_AUTHZ_OPA_URL` | conditional | no | Required when policy mode is shadow_opa or enforce_opa. |
| `AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS` | yes | no | OPA request timeout. |
| `AJENDA_BUDGET_POLICY_ENABLED` | yes | no | Enables budget-policy scaffolding. |
| `AJENDA_BUDGET_POLICY_OBSERVE_ONLY` | yes | no | Observe-only mode for budget policy (Bundle 5.2 default). |
| `AJENDA_BUDGET_POLICY_ENFORCE` | yes | no | Must remain false for Bundle 5.2. |
| `STRIPE_SECRET_KEY` | yes | yes | Stripe API secret (`sk_live_…` in production; `sk_test_` rejected at startup). |
| `STRIPE_WEBHOOK_SECRET` | yes | yes | Webhook signing secret (`whsec_…`). Required in production. |
| `STRIPE_PUBLISHABLE_KEY` | recommended | no | Stripe publishable key for future frontend checkout. |
| `STRIPE_PRICE_STARTER` | yes | no | Stripe Price ID for starter plan (`price_…`; admin/sales tier). |
| `STRIPE_PRICE_PRO` | yes | no | Stripe Price ID for pro plan (`price_…`; customer self-serve checkout). |
| `AJENDA_SIGNUP_ENABLED` | yes | no | Enable self-serve signup (default true). |
| `AJENDA_SIGNUP_VERIFY_URL_BASE` | yes | no | Base URL for verification links (must not be localhost in prod). |
| `AJENDA_EMAIL_PROVIDER` | yes | no | Must be `resend` in production (`logging` forbidden). |
| `AJENDA_RESEND_API_KEY` | yes | yes | Resend API key when `AJENDA_EMAIL_PROVIDER=resend`. |
| `AJENDA_EMAIL_FROM` | yes | no | From address for verification emails. |
| `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN` | yes | no | Must be `false` in production. |
| `AJENDA_SIGNUP_REQUIRE_IDEMPOTENCY_KEY` | no | no | Defaults to true in production when unset. |
| `AJENDA_CORS_ALLOWED_ORIGINS` | yes | no | Comma-separated origins when customer frontend is deployed. |
| `AJENDA_MISSION_INTERPRETER_ENABLED` | yes | no | Explicit rollout/rollback switch; disabled fails closed instead of restoring the legacy parser. |
| `AJENDA_MISSION_INTERPRETER_BASE_URL` | conditional | no | Private OpenAI-compatible `/v1` endpoint; required when the interpreter is enabled. |
| `AJENDA_MISSION_INTERPRETER_PRIVATE_HOST_ALLOWLIST` | yes | no | Exact comma-separated private inference hostnames allowed to receive interpretation input. |
| `AJENDA_MISSION_INTERPRETER_MODEL` | conditional | no | Model identifier loaded by the internal inference service. |
| `AJENDA_MISSION_INTERPRETER_TIMEOUT_SECONDS` | yes | no | Per-interpretation request timeout (maximum 300 seconds; in-stack CPU models often need 120–180). |
| `AJENDA_MISSION_INTERPRETER_MAX_TOKENS` | yes | no | Structured-output token ceiling. |
| `AJENDA_MISSION_INTERPRETER_API_KEY` | no | yes | Optional bearer token for an authenticated internal inference service. |

## Mission interpreter deployment

The interpreter is a language-normalization dependency of `POST /v1/missions/compose`, not a runtime worker and not a parallel mission-intelligence service. It receives the raw request plus a small allowlisted set of approved business-profile facts and returns schema-constrained, source-grounded interpretation data. It never receives credentials and cannot select abilities, grant permissions, approve a mission, admit work to a queue, or invoke a tool.

The default model is `qwen3:4b-instruct-2507-q4_K_M`. For a local Ollama installation:

```text
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama serve
```

Set `AJENDA_MISSION_INTERPRETER_BASE_URL=http://127.0.0.1:11434/v1` when the API runs on the host. Containers and Kubernetes pods must use a reachable private service address instead of loopback. Set `AJENDA_MISSION_INTERPRETER_PRIVATE_HOST_ALLOWLIST` to that endpoint's exact hostname; the client rejects every other host before opening a connection. The endpoint must support `/v1/chat/completions` and JSON-schema `response_format` structured output.

Rollout sequence:

1. Deploy and preload the model endpoint.
2. Verify schema output, latency, memory limits, and endpoint isolation in staging.
3. Enable `AJENDA_MISSION_INTERPRETER_ENABLED=true` for the API only.
4. Monitor structured interpreter failure codes and latency; raw prompts and model output must not be logged.

Compose also requires the tenant-scoped proposal database write to succeed. Confirmation row-locks that proposal and stores its receipt in the same transaction so retries—including retries with a new client key—cannot create duplicate missions. Treat `PROPOSAL_PERSIST_FAILED`, `PROPOSAL_STORE_UNAVAILABLE`, and `CONFIRM_RECEIPT_PERSIST_FAILED` as database availability alerts; all return HTTP 503 and fail closed.

Rollback sets `AJENDA_MISSION_INTERPRETER_ENABLED=false`. Compose then returns `INTERPRETER_DISABLED` with HTTP 503. Existing confirmed missions continue through deterministic compile/runtime paths because compile never calls the model. There is intentionally no template or legacy-parser fallback.

## Stripe and onboarding

Production startup (`Settings.validate_runtime_contract`) rejects:

- missing or invalid `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` (including `sk_test_` in production)
- missing or invalid `STRIPE_PRICE_STARTER` / `STRIPE_PRICE_PRO` (must start with `price_`)
- localhost `AJENDA_SIGNUP_VERIFY_URL_BASE` or `AJENDA_CORS_ALLOWED_ORIGINS` when signup is enabled
- `AJENDA_EMAIL_PROVIDER=logging`
- Resend without `AJENDA_RESEND_API_KEY`, `AJENDA_EMAIL_FROM`, `AJENDA_SIGNUP_VERIFY_URL_BASE`
- `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=true`

The verify URL base must resolve to a real page that calls `POST /v1/onboarding/verify-email`. The customer frontend ships `/verify-email` when the frontend image is deployed; in production set `AJENDA_SIGNUP_VERIFY_URL_BASE` to that host (for example `https://app.example.com/verify-email`).

## Generate encryption keys

Run once for each required Fernet key:

python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

Store these values in a secrets manager and expose them as:

AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY
AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY

Do not use deterministic development/test keys in production.

## Worker tenant assignment

`AJENDA_WORKER_TENANT_MODE` controls how workers choose tenant queues:

- **`single`** — poll one queue (`AJENDA_WORKER_TENANT_ID` required; must not be `default` in production).
- **`multi`** — round-robin across all active tenants from the `tenants` table (recommended for self-serve SaaS).

Per-tenant worker deployments remain valid for dedicated enterprise isolation.

## Production startup guardrails

Settings.validate_runtime_contract() rejects production deployments that use:

- local queue adapter,
- Redis adapter without AJENDA_QUEUE_URL,
- localhost OIDC issuer/JWKS,
- missing or invalid webhook/runtime secret encryption key,
- deterministic development/test webhook/runtime key,
- default or blank worker tenant id,
- invalid rate-limit settings,
- OPA modes without OPA URL,
- budget enforcement without budget policy enablement,
- budget enforcement with observe-only still enabled.
- enabled mission interpreter with a blank endpoint or model.
- invalid or credentialed mission interpreter endpoint (must be an `http(s)` `/v1` URL; credentials belong in the API-key secret).
- mission interpreter endpoint host outside its explicit private allowlist.

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
