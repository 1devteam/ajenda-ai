# Ajenda AI — v1.1.0

Ajenda AI is a governed, multi-tenant execution platform built for enterprise-grade runtime control, tenant isolation, compliance-aware task admission, authoritative queue-backed execution, bounded recovery, and evidence-based release decisions.

This repository contains both the application runtime and the runtime-proof layer used to validate whether the build is promotion-worthy.

**Canonical architecture (code-aligned, with Mermaid flowcharts):** [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md)

---

## System flow (summary)

```mermaid
flowchart LR
    subgraph Product["Customer product (staging-ready)"]
        UI["Customer UI :8080<br/>signup → verify → dashboard"]
        API["FastAPI /v1<br/>onboarding + account + billing + runtime"]
    end
    subgraph Runtime["Runtime authority"]
        DB["PostgreSQL + RLS"]
        Q["Redis queue"]
        W["WorkerLoop<br/>single or multi-tenant"]
    end
    Dev["Dev console /dev"] --> UI
    UI --> API
    API --> DB
    API --> Q --> W --> DB
```

**Paid customer loop:** signup → verify → bootstrap key → promote → account reads → Stripe checkout → webhook plan sync → ability-runtime task → worker execution. **Staging-ready** on Compose (`:8080`); **production cutover** still requires Resend, live Stripe, and GHCR frontend deploy — see [`ops/runbooks/paid-customer-loop-staging.md`](ops/runbooks/paid-customer-loop-staging.md) and [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md) §6.

---

## Product surface status (code truth)

| Surface | Status |
|---------|--------|
| Backend platform | Production-grade runtime, tenant isolation, queue/lease authority, recovery |
| Self-serve onboarding API | Implemented (`/v1/onboarding/*`) — signup, verify, resend, promote |
| Account self-service API | Implemented (`/v1/account/me`, `/plan`, `/usage`, `/billing`) |
| Provider credentials API | Implemented (`/v1/account/provider-credentials` + revoke/delete) |
| Ajenda central brain (standalone) | Implemented — durable `tenant_internal_records`, `web.research`, internal `gtm.crm_upsert` |
| Plugin discovery API | Implemented (`GET /v1/plugins`, action→plugin mapping) |
| HubSpot CRM adapter (optional plugin) | Implemented (`services/hubspot_crm_adapter`, TLS ingress in Compose/K8s) |
| Gmail + SMTP email plugins | Implemented — `external_email` credentials; `gtm.email_send` / `gtm.email_check` |
| Credentials UI | Implemented at `/credentials` (customer frontend) |
| Stripe billing API | Implemented — checkout, portal (`billing:manage`), signed webhook with dedup |
| Ability runtime API | Implemented — task launch, proofs, feature/quota gates |
| Customer frontend | Implemented — React Router app (`/signup`, `/verify-email`, `/dashboard`, `/billing`, `/tasks`) |
| Verify-email landing page | Implemented at `/verify-email` (Compose/K8s when frontend is deployed) |
| Frontend in deploy | Implemented — Compose `:8080`, K8s `ajenda-frontend`, GHCR image in release CI |
| E2E paid-customer proof | Implemented — `tests/integration/saas/test_paid_customer_loop_real.py` + staging curl script |
| Production stranger-ready | **Partial** — needs Resend, live Stripe, `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=false`, prod hostnames |

New signups provision on the **free** plan. `ability_runtime` (required for most side-effect abilities) is on **pro/enterprise** only. Workers support **`single`** (one `AJENDA_WORKER_TENANT_ID`) or **`multi`** (round-robin across active tenants); production defaults to **`multi`** — see ADR-0004.

### Ajenda central brain (standalone mode)

Ajenda runs fully without external CRM or email plugins:

1. **Internal contacts** — `record.search`, `record.read`, `record.write` persist to `tenant_internal_records` when a DB session is available.
2. **Web research** — `web.research` searches internal records and optionally fetches a public page snippet.
3. **Sales intelligence** — `sales.qualify`, `sales.score_lead`, `sales.recommend_next_action`, `sales.draft_followup` run locally.
4. **Internal CRM upsert** — `gtm.crm_upsert` without credentials writes to tenant internal records (`status=upserted_internal`).
5. **Plugin discovery** — `GET /v1/plugins` lists standalone vs optional plugins and standard CRM contract paths.

See [`docs/product/plugin-architecture.md`](docs/product/plugin-architecture.md).

### HubSpot CRM integration (optional plugin)

1. **Generate ingress TLS certs (first run / fresh clone)**

   ```bash
   bash deploy/compose/hubspot-crm-ingress/generate-certs.sh
   ```

   Certs are gitignored. `deploy/scripts/live-runtime-proof.sh` runs this automatically before compose build in CI.

2. **Start stack with adapter + TLS ingress**

   ```bash
   docker compose up -d hubspot-crm-adapter hubspot-crm-ingress api worker
   ```

   - Adapter health: `http://127.0.0.1:8088/health`
   - TLS ingress (worker target): `https://hubspot-crm-ingress:443` (Compose maps `8443:443`)

3. **Register credentials (UI or API)**

   - UI: sign in → **Credentials** → paste HubSpot personal access key
   - API: `POST /v1/account/provider-credentials` with `provider=external_crm`, `integration=hubspot`

4. **Launch governed CRM actions**

   - `crm.research` / `sales.research` → adapter `GET /v1/search`
   - `gtm.crm_upsert` → adapter `POST /v1/upsert`

5. **Platform master key mode (operator only)**

   - Set `AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED=true` and `AJENDA_HUBSPOT_PLATFORM_MASTER_KEY`
   - Tenants may register with `use_platform_master_key=true` (UI checkbox)
   - **Warning:** shared blast radius — prefer per-tenant keys in production

6. **Production hostname**

   - Set `AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST=crm-adapter.ajenda.example.com`
   - K8s ingress routes `crm-adapter.ajenda.example.com` → `hubspot-crm-adapter` service (TLS required; private egress bypass is forbidden in production)

---

## Repository legal status

This repository is proprietary.

- copyright ownership is documented in `COPYRIGHT`
- repository use restrictions and reserved-rights posture are documented in `NOTICE`
- no open-source license grant is provided in this repository

---

## What Ajenda AI is

Ajenda AI is designed to safely accept tenant-scoped work, enforce authentication and policy boundaries, move work through authoritative task and lease transitions, recover from worker/runtime failure without corrupting execution state, and preserve auditability across control-plane and runtime operations.

The system is built around these core guarantees:

- tenant isolation must hold at the HTTP, service, repository, and database layers
- queue-backed execution is authoritative for admitted work
- worker leases control execution ownership
- recovery must be bounded, observable, and safe
- policy/compliance gates must be able to prevent unsafe queue admission
- release confidence should come from runtime evidence, not assumptions

---

## Repository structure at a glance

| Layer | Components |
|-------|-----------|
| **Runtime** | `ExecutionCoordinator`, `RuntimeGovernor`, `RuntimeMaintainer`, `WorkerRuntimeService` |
| **Auth & Isolation** | OIDC/JWT + API keys, `TenantContextMiddleware`, `AuthContextMiddleware`, PostgreSQL RLS |
| **Queue** | Redis-backed queue adapter with lease handling and recovery support |
| **Compliance** | `PolicyGuardian`, governance events, pending-review policy path |
| **SaaS** | tenant lifecycle, onboarding, Stripe billing, plan enforcement, quota enforcement, feature gating |
| **Frontend** | Customer product UI (signup → billing → tasks) + `/dev` Runtime Ability Console |
| **Observability** | Prometheus metrics, audit events, governance events, validation artifacts |
| **Webhooks** | tenant-scoped outbound webhook management, reliability summaries, replay support |
| **Validation** | live runtime validation matrix, runner-backed artifact capture, release-gating scenarios |
| **Deployment** | Docker, Alembic, GitHub Actions, Kubernetes manifests |

---

## Architecture decision records (ADR)

Architecture governance for authority boundaries, schema compatibility, and readiness semantics is tracked in:

- `docs/architecture/ADR_INDEX.md`
- `docs/architecture/ADR-0001-authority-classification-doctrine.md`
- `docs/architecture/ADR-0002-schema-evolution-strategy.md`
- `docs/architecture/ADR-0003-readiness-semantics-doctrine.md`
- `docs/architecture/ADR-0004-worker-tenancy-strategy.md`
- `docs/architecture/ADR-0005-informed-autonomy-gate-policy.md`
- `docs/architecture/ADR-0006-external-platform-integration-doctrine.md`

These ADRs are accepted doctrines and should be updated alongside implementation/tests when authority semantics, schema contracts, or readiness behavior changes.

---

## Runtime architecture

### Startup contract

Application startup is fail-fast:

1. load settings
2. validate runtime contract
3. configure logging
4. initialize database runtime
5. build queue adapter
6. ping queue adapter
7. refuse startup if the queue is unreachable

This makes queue reachability part of the runtime authority contract rather than a soft optional dependency.

### Middleware order

Runtime behavior depends on middleware order.

Effective runtime order:

1. `SecurityHeadersMiddleware`
2. `CORSMiddleware`
3. `TenantContextMiddleware`
4. `AuthContextMiddleware`
5. `IdempotencyMiddleware`
6. `RateLimitMiddleware`
7. `RequestContextMiddleware`

Important boundary rule:

- tenant context must execute before auth resolution at runtime so API key lookups are scoped to the validated tenant

### Probe and readiness contract

Infrastructure probes remain stable at root:

- `/health`
- `/readiness`

Versioned system probes are mounted under `/v1/system`:

- `/v1/system/health` (deprecated alias of `/health`)
- `/v1/system/readiness`
- `/v1/system/status`

Current contract distinction:

- health probes are liveness surfaces and should stay lightweight
- readiness probes are dependency-readiness surfaces and must represent whether required runtime dependencies are usable
- tenant-facing system status remains protected by tenant/auth envelope and tenant-scoped database access

Current implementation note:

- current `main` has the stable route surfaces above
- dependency-readiness precision is an active hardening target; follow-up work should keep health lightweight while making readiness explicitly reflect database plus configured queue readiness with sanitized failure responses
- this README update identifies the follow-up contract; it does not implement or prove readiness dependency behavior by itself

### API versioning

- infrastructure probes remain stable at root:
  - `/health`
  - `/readiness`
- business and operational APIs are mounted under `/v1`
- current route families include:
  - `/v1/auth/*`
  - `/v1/ability-runtime/*`
  - `/v1/api-keys/*`
  - `/v1/billing/*`
  - `/v1/onboarding/*`
  - `/v1/account/*`
  - `/v1/mission-brief/*`
  - `/v1/missions/*`
  - `/v1/capabilities/*`
  - `/v1/capability-adapters/*`
  - `/v1/business-profile/*`
  - `/v1/evidence/*`
  - `/v1/outcome-reviews/*`
  - `/v1/retrieval-contracts/*`
  - `/v1/tasks/*`
  - `/v1/workforces/*`
  - `/v1/plugins/*`
  - `/v1/branches/*`
  - `/v1/runtime/*`
  - `/v1/operations/*`
  - `/v1/system/*`
  - `/v1/observability/*`
  - `/v1/webhooks/*`
  - `/v1/admin/*`

---

## Current contract inventory

The following contract surfaces exist on `main`. Some are runtime-enforced contracts, some are database/schema-enforced contracts, some are metadata/read-model contracts, and some are declaration contracts whose runtime binding is intentionally deferred. This inventory describes each contract's current authority boundary; it is a navigation map, not a replacement for the source files, tests, validation artifacts, or live proof output.

The `Current proof/backing` column identifies the strongest known verification surface for the row. It must not be read as full end-to-end proof for every behavior in that row.

The machine-readable authority map for these surfaces is maintained in `docs/contracts/authority-ledger.v1.yaml`.
That ledger is normative for authority-class intent and required proof surfaces when contract boundaries evolve.

| Contract area | Current source of truth | Current behavior / authority boundary | Current proof/backing |
|---|---|---|---|
| Runtime startup | `backend/main.py`, `backend/app/config.py`, queue adapter construction | startup validates runtime configuration and queue reachability before serving | unit/config tests, deployment proof |
| Authentication modes | auth middleware, OIDC/JWT validation, API-key services and routes | supports bearer/OIDC and tenant-scoped API-key flows with fail-closed invalid credential handling and cross-tenant rejection | auth/unit/contract tests |
| Tenant/auth envelope | middleware, auth services, tenant DB dependencies, RLS migrations | tenant-scoped routes require valid tenant/auth envelope; public probes stay public | contract auth/isolation tests |
| SaaS quota and plan enforcement | tenant plan/usage models, tenant repository, quota service, task/mission/API-key routes | tenant lifecycle, feature limits, and quota checks gate platform use before unsafe over-consumption | unit/contract service and route tests |
| Self-serve onboarding | `backend/api/routes/onboarding.py`, `tenant_onboarding_orchestrator.py`, `tenant_members`, signup abuse tables | public signup/verify/resend; bootstrap API key on verify; promote to `tenant_operator`; prod email via Resend | unit/contract/integration onboarding tests |
| Stripe billing | `backend/api/routes/billing.py`, `billing_stripe_integration.py`, `stripe_webhook_events` | checkout/portal for authenticated tenants; public webhook with signature verify and event dedup; plan sync via lifecycle service | unit/contract/integration Stripe tests |
| Ability runtime (product API) | `backend/api/routes/ability_runtime.py` | exposes worker-backed actions; gates `ability_runtime` and `gtm` features by plan; queues tasks through ExecutionCoordinator | unit/contract tests, integration runtime tests |
| Account self-service | `backend/api/routes/account.py`, `account_service.py` | `/v1/account/me`, `/plan`, `/usage`, `/billing`; bootstrap key blocked from billing reads | unit/contract tests |
| Customer frontend | `frontend/src/pages/*`, `App.tsx`, `api/client.ts` | signup/verify/promote flow, dashboard, billing, tasks; `/dev` retains ability-runtime console | frontend build CI, deployment contract tests |
| Queue-backed execution | `ExecutionCoordinator`, queue adapters, task routes | admitted runtime work must be represented in DB and queue authority | integration/runtime tests, live proof |
| Worker lease ownership | `WorkerRuntimeService`, `WorkerLease`, runtime transitions | worker leases control claim/start/complete/fail authority | runtime integration tests, live proof |
| Recovery reconciliation | `RuntimeMaintainer`, `QueueAdapter` recovery methods | stale work recovery uses queue evidence, expires stale leases, and avoids synthetic replacement work after payload loss | runtime recovery integration tests |
| Dead-letter inspection/retry | queue adapters, `OperationsService`, operations routes | dead-letter retry/inspection reconciles DB and queue evidence with tenant scope | contract/integration operations tests |
| Governance and audit evidence | audit/governance event models, policy path, runtime services, validation artifacts | admission, denial, completion, policy, and recovery decisions must leave reviewable evidence where required | unit/contract/integration tests, live proof |
| Compliance and policy gates | `PolicyGuardian`, mission/task compliance fields | compliance metadata and policy checks can prevent unsafe queue admission and route work to review | unit/contract tests |
| Durable mission plans | `MissionPlan`, `MissionPlanRepository`, mission routes, migrations `0017`–`0018`, backfill `0031` | `POST/PUT /v1/missions/{id}/plan` write to `mission_plans`; `GET` prefers table, falls back to legacy `metadata_json["mission_plan"]`; legacy PUT payloads preserved under `legacy_v1` | unit/API/repository/migration contract tests |
| Capability registry | capability routes, models, repositories, migrations | capabilities declare task types, schemas, required permissions/tools, risk, approval, evidence, constraints, enabled state, scope, version, and schema version; registry declarations do not execute work or bind handlers by themselves | unit/API/repository/migration contract tests |
| Capability execution adapters | adapter routes, models, repositories, migrations | adapters declare capability bindings, execution mode, input/output contracts, side-effect class, timeout/retry/idempotency expectations, and evidence expectations; adapter records do not execute work or register runtime handlers by themselves; an adapter contract is not a worker-callable runtime binding unless a separate binding/execution contract explicitly makes it so | unit/API/repository/migration contract tests |
| Business Profile | business-profile routes, models, repositories, migrations | Business Profile stores durable tenant-approved reusable context and profile update suggestions; it is not a mission, does not replace `MissionCreate`, does not generate Mission Briefs, and has no runtime authority | contract/API/repository/migration tests |
| Mission Brief read model | mission-brief route and mission-brief service | Mission Brief drafts combine approved Business Profile context, current mission intent, and request context into structured read-only readiness output with Missing Info, MissionCreate prefill suggestions, provenance, conflicts, and authority flags; they do not create missions, runtime work, profile truth, or memory | unit/API/service tests |
| Task graph contracts | mission metadata normalizer and task-graph routes | task graphs are normalized metadata contracts; legacy v1 shape requires explicit `allow_legacy_v1` on mission create or pre-existing stored legacy graphs | unit/API/domain tests |
| Mission-to-runtime bridge contracts | mission materialization/admission/readiness/preview/worker admission endpoints and mission metadata keys | mission graphs move toward runtime through explicit, tenant-scoped bridge stages; those stages must not be collapsed into one implicit execution path; each stage records metadata or performs one bounded mutation and does not skip queue, lease, dispatcher, or recovery authority | unit/API/domain tests |
| Evidence records | evidence routes, models, repositories, migrations | evidence records store tenant-owned proof/provenance for missions, graph nodes, materializations, tasks, capabilities, adapters, artifacts, trust, and collection state without executing work or scoring outcomes | unit/API/repository/migration contract tests |
| Outcome reviews | outcome-review routes, models, repositories, migrations | outcome review records store review decisions, findings, confidence, gaps, and human-approval fields for mission result claims; they do not autonomously generate decisions or mutate runtime state unless a future explicit reviewer/scoring layer exists | unit/API/repository/migration contract tests |
| Retrieval and recall contracts | retrieval-contract routes, models, repositories, migrations | retrieval contracts govern future memory retrieval requests, filters, provenance, status, supersession, and revocation without generating embeddings, running vector search, or mutating runtime state | unit/API/repository/migration contract tests |
| Mission lifecycle read model | mission lifecycle route and mission/product contract aggregators | lifecycle reads aggregate mission, intake, plan, graph, materialization, evidence, outcome, memory, retrieval, completeness, and missing-next-step state without mutating or executing runtime work | unit/API tests |
| Webhook delivery and replay | webhook routes, models, repositories, services, migrations | tenants can manage endpoints, delivery records, replay flows, reliability summaries, signing, and encrypted signing-secret storage | unit/contract/integration tests |
| Deployment runtime contract | Compose/K8s manifests, production env contract, live proof script | deployment surfaces use canonical `AJENDA_*` env aliases, supported entrypoints, probes, metrics path, and prod-like proof stack | deployment tests, live-runtime proof |
| Observability contract | observability route, Prometheus config, live proof | metrics are exposed at `/v1/observability/metrics` and scraped by Prometheus | contract/deployment tests, live proof |
| Validation matrix and artifacts | validation docs, runner scripts, artifact schema, release-gating scenarios | release-gating scenarios define expected evidence, dynamic run truth, artifact provenance, safety classes, and promotion-blocking semantics | validation docs, runner, tests |

---

## Runtime validation and release gating

Ajenda includes a live runtime validation system, not just a test suite.

Primary files:

- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`
- `scripts/validation/live_runtime_matrix.sh`
- `scripts/validation/lib.sh`
- `artifacts/validation/README.md`

This validation layer exists to prove:

- what must always work
- what must never happen
- what evidence is required to trust a scenario result
- whether a build is safe to promote

The validation system currently includes:

- a release-gating scenario set
- broader runtime scenarios
- evidence capture across API, DB, Redis, audit, and worker logs
- safety classes for read-only, tenant-scoped mutation, and global mutation scenarios
- recovery summary validation that includes dead-letter outcomes
- prod-like live runtime proof for health/readiness, worker execution, observability metrics, audit/lineage evidence, Prometheus scrape health, and Redis lease cleanup
- focused GitHub-side verification for recovery hardening and runtime-validation paths

Validation artifacts are written to:

- `artifacts/validation/<timestamp>/<scenario-id>/...`

Each scenario can capture combinations of:

- API response status/body
- database evidence
- Redis evidence
- audit/governance evidence
- worker log evidence

### Prod-like live runtime proof

The prod-like live runtime proof is documented in:

- `docs/validation/live-runtime-proof-release-gate.md`

The executable proof script is:

- `deploy/scripts/live-runtime-proof.sh`

This proof validates a running Compose stack (including HubSpot ingress TLS cert generation when missing), root and versioned health/readiness probes, real queue-backed worker completion, released lease state, task output lineage, worker completion audit evidence, live Prometheus metrics at `/v1/observability/metrics`, Prometheus scrape-target health, Redis lease cleanup, GTM `gtm.lead_enrich`, and the brain capstone slice.

On every push to `main`, `.github/workflows/ci.yml` runs this proof after integration tests and docker build succeed. Operators can also dispatch `.github/workflows/live-runtime-proof.yml` manually.

### Paid customer loop staging proof

For the stranger-ready product path (customer UI + onboarding + account APIs):

- Runbook: [`ops/runbooks/paid-customer-loop-staging.md`](ops/runbooks/paid-customer-loop-staging.md)
- Env template: `deploy/compose/.env.staging.example` → copy to `.env.staging`, then sync to `deploy/compose/.env.prod`
- Script: `deploy/scripts/paid-customer-loop-staging-proof.sh`
- Integration test: `tests/integration/saas/test_paid_customer_loop_real.py`

```bash
cp deploy/compose/.env.staging.example deploy/compose/.env.staging
# edit secrets, then:
cp deploy/compose/.env.staging deploy/compose/.env.prod
docker compose --env-file deploy/compose/.env.prod \
  -f deploy/compose/docker-compose.prod.yml up -d --build
bash deploy/scripts/paid-customer-loop-staging-proof.sh
```

Customer UI: http://localhost:8080 — API (direct): http://localhost:8000

GHCR images (including frontend) publish on merge to `main` via `.github/workflows/release.yml`. Local pull:

```bash
docker login ghcr.io -u <github-username> --password-stdin   # paste PAT with read:packages
```

---

## Local development

Docker Compose is optional — use it when you need Postgres, Redis, or the worker locally. Unit and contract tests run without a running stack (integration tests use Testcontainers).

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Install project in editable mode
pip install -e ".[dev]"

# 3. (Optional) Start infrastructure
docker compose up -d

# 4. (Optional) Run migrations — use localhost when invoking alembic from the host:
#    AJENDA_DATABASE_URL=postgresql+psycopg://ajenda:ajenda@localhost:5432/ajenda alembic upgrade head

# 5. Start the API (requires DB/queue if exercising runtime paths)
uvicorn backend.main:app --reload
```

### Testing

```bash
# Unit / non-integration tests
python -m pytest -m "not integration"

# Integration tests (requires Docker; fixtures start isolated Postgres + Redis with Testcontainers)
python -m pytest -m integration

# Full suite
python -m pytest
```

Integration tests do not use the root `docker-compose.yml` stack or fixed localhost service containers. The `tests/integration/conftest.py` fixtures start isolated Testcontainers-managed `postgres:16-alpine` and `redis:7-alpine` containers, run Alembic migrations against that temporary Postgres instance, and inject the generated database and Redis URLs into the test environment.

### Validation runner

```bash
# All supported validation scenarios
scripts/validation/live_runtime_matrix.sh

# Read-only scenarios only
scripts/validation/live_runtime_matrix.sh --group read-only

# One scenario
scripts/validation/live_runtime_matrix.sh --scenario RG-03
```

---

## Validation environment variables

| Variable | Purpose |
|----------|---------|
| `AJENDA_API_URL` | Base URL for API validation calls |
| `AJENDA_DB_URL` | Postgres connection string for evidence queries |
| `AJENDA_REDIS_URL` | Redis URL for queue evidence |
| `AJENDA_TENANT_ID` | Tenant UUID for tenant-scoped scenarios |
| `AJENDA_AUTH_HEADER` | Auth header for protected scenario execution |
| `AJENDA_LOG_SOURCE` | Worker log file path or Docker container name |

Optional scenario-specific IDs:

- `AJENDA_SAMPLE_TASK_ID`
- `AJENDA_FORCE_FAIL_TASK_ID`
- `AJENDA_DEAD_LETTER_TASK_ID`
- `AJENDA_PENDING_REVIEW_TASK_ID`

---

## Safety model for validation runs

The validation system uses three safety classes:

- `SAFE_READ_ONLY`
- `TENANT_SCOPED_MUTATION`
- `GLOBAL_MUTATION`

Operational meaning:

- read-only checks are suitable for broad repeated use
- tenant-scoped mutations change one tenant's state and require scoped care
- global mutation scenarios must run only where cross-tenant operational mutation is acceptable

See the validation docs for the current execution-policy semantics.

---

## Current strengths

Ajenda currently has strong foundations in:

- fail-closed auth behavior
- tenant envelope enforcement
- queue-backed execution
- lease-aware worker runtime
- bounded runtime recovery
- dead-letter inspection and retry surfaces
- durable mission planning and task graph contract layers
- capability registry and adapter declaration contracts
- mission-to-runtime bridge contracts
- evidence, outcome review, and retrieval governance layers
- quota and SaaS lifecycle support
- multi-tenant worker scheduling (`single` / `multi` modes)
- webhook reliability and replay support
- live runtime validation artifacts and release-gating structure
- deployment runtime proof with Prometheus and OpenTelemetry collector coverage

---

## Current hardening focus

Backend runtime, SaaS plumbing, customer frontend, account APIs, deploy wiring, and E2E paid-loop proof are in place for **staging**. Production guards and hostname contracts are enforced at startup and in deployment tests. Before launch:

1. Replace placeholder host `ajenda.example.com` with your real domain across ingress, ConfigMap, and `.env.prod`
2. Set live Stripe (`sk_live_`, `price_` IDs) and Resend secrets; register webhook at `https://<domain>/v1/billing/webhook/stripe`
3. Run staging runbook + `test_paid_customer_loop_real` against the production-like host

Ongoing platform hardening (unchanged):

- README, `SYSTEM_ARCHITECTURE.md`, validation docs, tests, and implementation alignment
- authoritative runtime proof for recovery, dead-letter, and lease-bound execution
- release confidence from runtime evidence, not doc-only posture

Recent milestones:

- **Onboarding & billing:** tenant members, signup abuse guard, onboarding routes, bootstrap/promote keys, Stripe webhook dedup, GTM / ability-runtime quota and feature gates
- **Runtime cleanup (Phases 0–3):** canonical execution-path contracts, `mission_bridge/` service extraction, unified claim-holder semantics, legacy `POST /missions/{id}/queue` deprecation, `/v1/system/health` deprecated alias of `/health`
- **Mission plans (Phase 4):** durable `mission_plans` table is canonical; `PUT /plan` writes table only; legacy metadata read-only + `0031` backfill migration; `allow_legacy_v1` opt-in on mission create (default false)
- **Worker tenancy (Phase 5):** `AJENDA_WORKER_TENANT_MODE=multi` round-robin across active tenants (ADR-0004); production deploy defaults updated
- **Paid customer product:** account APIs, customer frontend (router + pages), Compose/K8s frontend deploy, GHCR frontend image CI, E2E integration test + staging curl proof
- **Alembic head:** `0033_tenant_internal_records`
- **Live proof CI:** `main` push runs Live Runtime Proof after integration + docker build (see `docs/validation/live-runtime-proof-release-gate.md`)

---

## Quality gates

Before opening a PR, run at minimum:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/migration_seed_contract_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

Run integration tests, migration round-trip checks, and live runtime proof when your change affects runtime behavior, queueing, recovery, isolation, release-gating, compose deploy, or validation semantics.

---

## Migrations

| ID | Description |
|----|-------------|
| 0001 | Initial schema |
| 0002 | Add API key records |
| 0003 | Row-Level Security policies |
| 0004 | Add recovering task state and worker lease recovery foundation |
| 0005 | Add compliance fields to execution tasks |
| 0006 | SaaS tenant lifecycle |
| 0007 | Webhook endpoints and deliveries |
| 0008 | Add retry count and pending-review state |
| 0009 | Add webhook secret ciphertext |
| 0010 | Align free-plan quota contract |
| 0011 | Add capability registry contracts |
| 0012 | Add capability execution adapter contracts |
| 0013 | Add evidence records |
| 0014 | Add outcome reviews |
| 0015 | Add memory promotion records |
| 0016 | Add retrieval contracts |
| 0017 | Add mission plans |
| 0018 | Harden mission plan status values |
| 0019 | Harden retrieval contract persisted values |
| 0020 | Expand evidence/outcome lifecycle checks |
| 0021 | Seed GTM capability catalog |
| 0022 | Business profiles |
| 0023 | Expand adapter side effects |
| 0024 | Provider runtime credentials |
| 0025 | stripe_customer_id on tenants |
| 0026 | Seed ability_runtime + gtm on pro/enterprise |
| 0027 | stripe_webhook_events dedup |
| 0028 | tenant_members |
| 0029 | API key bootstrap fields |
| 0030 | signup abuse tables |
| 0031 | backfill mission_plans from legacy mission metadata |
| 0032 | OIDC login intents and customer auth sessions |
| 0033 | tenant_internal_records for Ajenda standalone brain mode |

**Alembic head:** `0033_tenant_internal_records`

---

## Source-of-truth docs

Start here when working on product direction and current runtime behavior.
`PROJECT_SPEC.md` is the canonical specification; `SYSTEM_ARCHITECTURE.md` is the code-aligned visual map.

- `PROJECT_SPEC.md`
- `README.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/product/mission-based-ai-core.md`
- `docs/product/GTM_SELF_SELLING_ARCHITECTURE.md`
- `docs/product/GTM_CAPABILITY_CATALOG.md`
- `docs/policies/OUTBOUND_COMMUNICATION_POLICY.md`
- `docs/deployment/production-env-contract.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`
- `artifacts/validation/README.md`
- `docs/README.md`
- `docs/PROJECT_STATE_REPORT.md`
- `docs/SAAS_ARCHITECTURE.md`
- `docs/policies/DOCS_FRESHNESS_POLICY.md`
- `docs/contracts/authority-ledger.v1.yaml`
- `docs/contracts/observability-metrics-route-contract.md`

---

## Known follow-up contract audits

The following areas are intentionally identified for follow-up review rather than silently assumed complete:

- readiness dependency precision: keep health lightweight while making readiness explicitly reflect database and configured queue dependency truth with sanitized failure responses
- approved-contract replay audit: for each inventory row, compare README/docs claims against code, migrations, routes, services, repositories, tests, and live/runtime proof surfaces; classify the row as runtime-enforced, schema-enforced, metadata-only, read-only, declaration-only, partial, future-boundary, or drift
- mission-to-runtime bridge replay: verify every materialization, admission, readiness, preview, worker-claim, worker-start, and worker-run bridge remains bounded to its documented authority and has not collapsed multiple authority stages into one implicit execution path
- capability and adapter enforcement boundary audit: verify declaration contracts remain separate from runtime handler binding until an explicit binding layer exists
- evidence/outcome/retrieval lifecycle audit: verify proof, review, and recall records remain governance contracts and do not mutate runtime execution state
- webhook reliability contract replay: verify endpoint, delivery, signing-secret encryption, replay, and reliability summary behavior remain aligned
- SaaS/quota admission replay: verify plan limits and quota accounting still gate admission paths consistently
- mission approval/admission semantics: classify which approval/admission fields are enforced gates and which are advisory metadata
- validation matrix freshness: keep release-gating rows aligned with protected control-plane routes, current proof scripts, current artifact semantics, and current test evidence; known stale public-route wording around recovery must be refreshed before using the matrix as executable prompt context
- project state report freshness: keep `docs/PROJECT_STATE_REPORT.md` aligned with migration head, CI proof posture, and deployment surfaces on each release cycle
