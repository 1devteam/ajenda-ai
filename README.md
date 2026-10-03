# Ajenda AI — v1.2.0

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
| Gmail + SMTP email plugins | Implemented — credential-bound `gtm.email_send` / `gtm.email_check`; missing credentials fail closed |
| Google Calendar / Contacts connectors | Implemented — separate OAuth connect; external actions never silently simulate in production |
| Credentials / Connections UI | Implemented at `/credentials` and `/connections` (OAuth-first Google cards) |
| Mission composition engine | Implemented — plain language → structured `MissionIntent` → jobs → proposal; restatement on incomplete input |
| Product knowledge shelf | Implemented — versioned, tenant-scoped product capabilities project through profile, CRM, retrieval, GTM, and vertical shelves |
| Deterministic algorithm intelligence | Implemented — hashed, provenanced read-model results are recomputed on persisted composition reads and fail closed on drift |
| Mission result semantics | Implemented — runtime/deliverable acceptance is separate from evaluated business-goal status |
| Command Center mission metrics | Implemented — tenant-wide mission totals/completions drive success rate; active work refreshes the read model every 15 seconds |
| Bounded browser observation | Implemented — read-only artifacts expose request vetting, DNS pinning, allowed hosts, engine, and ephemeral-context provenance |
| Governed vertical operations | Implemented — `/v1/vertical-ops/*` template planning and bounded queue admission; Phase C templates remain plan-only |
| Stripe billing API | Implemented — checkout, portal (`billing:manage`), signed webhook with dedup |
| Ability runtime API | Implemented — task launch, proofs, feature/quota gates |
| Customer frontend | Implemented — React Router app (`/signup`, `/signin`, `/missions`, `/connections`, `/dashboard`, `/billing`) |
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

### Product knowledge and algorithmic integrity

Ajenda's product knowledge is a declarative shelf, not an execution system. The
canonical catalog lives in `backend/services/ontology/product_knowledge.py` and
is projected through approved Business Profile facts, tenant CRM records,
governed retrieval, existing GTM outcomes, and vertical context. Malformed or
duplicate tenant entries fail closed. Catalog entries cannot register handlers,
resolve credentials, invoke tools, approve work, or grant runtime authority.

Composition algorithms are deterministic, versioned read-model evaluations.
Each result records its registry identity, input hash, confidence, evidence
references, provenance, and `grants_execution_authority=false`. When a
composition record is read back, non-empty algorithm results are recomputed
against the current composition inputs; stale, tampered, unknown, or
authority-bearing results are rejected. Historical records without algorithm
results remain readable for compatibility.

The Command Center success rate is calculated from tenant-wide mission
aggregates rather than only the newest mission-list page. While active work is
present, the dashboard refreshes those aggregates every 15 seconds, so a
worker-completed mission is reflected without a manual reload. See the full
GRAFT+ map and runtime proof in
[`docs/architecture/PRODUCT_KNOWLEDGE_SHELF_MAP.md`](docs/architecture/PRODUCT_KNOWLEDGE_SHELF_MAP.md).

### External connector truthfulness

External providers are governed separately from Ajenda's standalone capabilities:

- Missing provider credentials fail closed by default. Simulated external results require explicit non-production opt-in through `AJENDA_ALLOW_SIMULATED_EXTERNAL`; production ignores that opt-in.
- Connector handlers governed by ADR-0009 never replace a credentialed provider exception with simulated success. The generic `provider.external_read` foundation separately records the returned HTTP status as read evidence, including non-2xx responses.
- Explicit provider requests remain provider-bound. For example, HubSpot-sourced research cannot fall back to public web research or Ajenda's internal records.
- Mission composition rejects known unsupported explicit Gmail operators and unsupported CRM scopes. Gmail retains each material `for` clause and translates supported week, month, today, and 24-hour language into bounded date operators; other natural-language time expressions are not yet guaranteed as structured filters.
- CRM writes that require an external connector report `connection_required` when the connector is unavailable; they do not claim success by writing one aggregate placeholder locally.

The governing decision and compatibility notes are in [`ADR-0009`](docs/architecture/ADR-0009-external-connector-truthfulness.md).

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

   - UI: sign in → **Connections** (`/connections` or `/credentials`) → paste HubSpot personal access key
   - Google connectors (Gmail / Calendar / Contacts) use **separate OAuth buttons** (identity login stays `openid email profile` only)
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

- health probes stay lightweight liveness checks (`/health`, deprecated `/v1/system/health`)
- readiness probes delegate to `ReadinessEvaluatorService`, which pings configured database and queue dependencies and returns `503` with sanitized reasons (`DATABASE_UNAVAILABLE`, `QUEUE_UNAVAILABLE`, `DEPENDENCY_UNAVAILABLE`) when either dependency is unavailable
- readiness payloads expose `dependencies.database.status` and `dependencies.queue.status`; missing optional dependencies report `skipped`
- proof: `tests/unit/services/test_readiness_evaluator_service.py`, `tests/contract/api/test_health_route.py`, matrix rows CP-06 and CP-07

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
  - `/v1/crm/*`
  - `/v1/review-queue/*`
  - `/v1/branches/*`
  - `/v1/runtime/*`
  - `/v1/operations/*`
  - `/v1/system/*`
  - `/v1/observability/*`
  - `/v1/vertical-ops/*`
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
| Queue/DB claim convergence | `WorkerRuntimeService.claim_next_task`, queue payload enqueue timestamps | recent taskless claims are released during the bounded commit-visibility window; stale payloads without a matching tenant task are quarantined instead of requeued forever | worker transaction tests, live mission proof |
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
| Mission deliverable result semantics | `WorkerRuntimeService`, `revops_deliverable.py`, goal evaluation action | mission acceptance describes runtime execution and requested-deliverable completion; `result_semantics.business_outcome_status` independently reports the evaluated goal result. Without durable Goal/KPI authority, evaluation remains instruction-only and reports explicit evidence gaps | unit/service tests, live mission artifacts |
| Fixture and browser evidence truth | `standalone_actions.py`, `web_actions.py`, evidence bridge | local fixtures remain `real=false` with `source=local_fixture` and `fixture://` identities; browser observations preserve governed network provenance in artifacts and evidence | tool unit tests, live mission artifacts |
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
- **Alembic head:** `0036_composition_thread`
- **Live proof CI:** `main` push runs Live Runtime Proof after integration + docker build (see `docs/validation/live-runtime-proof-release-gate.md`)
- **Outcome-loop intelligence:** deterministic coverage/applicability assessment, epistemic context, deliverable lifecycle reconciliation, and semantic lattice provenance are implemented before and alongside governed runtime execution
- **Semantic lattice:** shared GTM/business concepts now compose with local-service, field-service, professional-services, healthcare, SaaS, e-commerce, and industry overlays including HVAC, roofing, plumbing, electrical, landscaping, pest control, legal, dental, recruiting, and advertising
- **Advertising boundary:** advertising concepts (campaign, audience, creative, spend, impressions, clicks, conversions) are declarative composition vocabulary; the existing ads role remains catalog-only until a governed provider path is proven

---

## Established build workflow: UPG/LAP + GRAFT+

GRAFT terminology is intentionally precise: **GRAFT1st** is used to design a new program or bounded
system before its first line of implementation; **GRAFT+** is used to understand and change an
existing program. Ajenda AI is an existing program, so repository change work uses GRAFT+.

Non-trivial layer, runtime, tool, networking, persistence, security, or workflow work follows the
repository's established [GRAFT+ workflow](docs/development/GRAFT_PLUS_WORKFLOW.md):

1. verify implementation, tests, migrations, and runtime state as the source of truth;
2. complete UPG/LAP responsibility, dependency, pitfall, invariant, and proof review;
3. use the canonical dependency graph to measure the actual blast radius and select proof;
4. build the complete graph-supported change—the workflow does not require the smallest patch;
5. run targeted and graph-selected gates, then inspect real runtime artifacts for hidden errors;
6. reconcile docs only after implementation and evidence agree.

Ambitious or exploratory work is allowed. Unverified authority, tenant scope, persistence,
side-effect, or retry assumptions are not. GRAFT+ is both a build guide and a test of the graph's
coverage; unmapped files, missing invariants, and unexpected runtime artifacts are workflow
findings to classify or resolve rather than reasons to silently narrow the intended build.

### R&D lanes: proven change and frontier exploration

Ajenda's research and development process now has two deliberately separate GRAFT+ lanes:

- **Standard GRAFT+** works from the existing implementation and produces the build-ready impact,
  invariant, proof, runtime-artifact, and reconciliation record.
- **GRAFT+ Frontier Track** captures ambitious hypotheses, unconventional mechanisms, alternative
  architectures, counterfactuals, reversible experiments, unknowns, promotion criteria, rollback,
  and a kill switch.

Both lanes use the same canonical graph, but their artifacts are generated independently and can be
compared side by side. Frontier work is explicitly research evidence—not runtime authority. It cannot
dispatch tasks, call providers, resolve credentials, register handlers, approve side effects, or
become production truth. A frontier proposal becomes implementation work only after an explicit
promotion review and a normal GRAFT+ impact/proof pass.

Run the frontier validator with the standard impact report:

```bash
python scripts/validation/graft_plus_frontier.py \
  --frontier-spec docs/templates/graft-plus-frontier-spec.v2.json \
  --impact-report artifacts/graph-impact-report.json \
  --output artifacts/frontier-validation.json \
  --comparison-output artifacts/frontier-side-by-side.json
```

The full contract is documented in [GRAFT+ Frontier Track](docs/development/GRAFT_PLUS_FRONTIER_TRACK.md).

New frontier proposals use schema version 2. They must name owners, state unknowns and expected
failure modes, define measurable experiments with durable artifact paths, and retain promotion
evidence. A validator pass proves contract and authority separation only; it does not prove the
hypothesis or execute the experiment.

Canonical ownership and compatibility for the three outcome graphs are declared in
[`outcome-graph-ownership.v1.json`](docs/contracts/outcome-graph-ownership.v1.json) and checked by
`python scripts/validation/outcome_graph_ownership_check.py`. This manifest is governance metadata;
it does not grant any graph runtime authority. New composition artifacts also persist the same
ownership/version snapshot as `GraphLineage`; older records remain readable with compatibility
defaults and preserve their original know-how/materialization provenance.

### What the GRAFT+ shift has taught us

The history of using GRAFT+ in Ajenda shows that it is more than a change checklist. It is an
architectural intelligence and discovery process:

- It exposed hidden blast radius around mission composition, coverage, evidence, queues, workers,
  browser safety, tenant boundaries, and deliverables before those relationships were obvious.
- Runtime-artifact review found issues that green mission status concealed, including stale container
  images, queue/database visibility races, shared queue contamination, fixture data presented as real,
  lost identity provenance, and business-goal completion being confused with runtime completion.
- It allowed larger coherent changes while keeping ActionRegistry, TaskDispatcher,
  WorkerRuntimeService, tenant isolation, evidence, and side-effect controls authoritative.
- It turned graph gaps, unmapped files, contradictory artifacts, and stale documentation into visible
  findings rather than silent assumptions.

The process also has real limits:

- A passing graph report does not prove live infrastructure health or business truth.
- A mission artifact can look complete while shared queue, worker, persistence, or provenance state is
  unhealthy; adversarial runtime inspection is required.
- Generated graph output is temporary, so the builder, semantic overlay, tests, and runtime artifacts
  remain the durable sources of truth.
- GRAFT+ adds time and review overhead, and its findings can be noisy until they are reconciled.
- Frontier proposals are hypotheses, not implementations; treating them as authority would defeat the
  separation this workflow is designed to protect.

The practical realization is that Ajenda now has two complementary R&D behaviors: standard GRAFT+
makes existing-system change legible and provable, while the Frontier Track makes ambitious
possibilities explicit without allowing speculation to mutate production behavior. Their value comes
from comparison, runtime evidence, and honest reconciliation—not from the graph artifact alone.

### Outcome-loop intelligence and semantic lattice

Ajenda's composition layer now records more than selected actions. A mission can carry a deterministic
coverage assessment (known fixture scope/capacity or explicitly unknown provider/CRM capacity), an
epistemic context (source class, confidence, freshness, missing evidence, contradiction state, and
an explicit uncertainty budget),
and a deliverable lifecycle snapshot that is reconciled against materialized artifacts. Blocked coverage
cannot silently coexist with materialized runtime work: such drift is surfaced as a contradictory
lifecycle state. Durable shadow
previews now capture the planned graph and expected artifacts before admission, and the worker-owned
read-model refresh compares those expectations with later governed runtime artifacts. These records
remain read models and grant no runtime authority; missing or unexpected artifacts remain visible.
The read-only proposal shadow-preview endpoint validates those server-owned expectations before
confirmation without creating runtime work.
The periodic worker maintenance pass also refreshes tenant-scoped deliverable read models through
the same canonical lifecycle transformer used after task completion. This keeps freshness and
artifact reconciliation moving even when no new task has just completed; it does not create work,
resolve credentials, or change queue authority.
The October 3, 2026 outcome-loop checkpoint proves supported fixture execution, unsupported and
over-capacity fail-closed composition, and insufficient-public-evidence fail-closed runtime behavior.
It also verifies that materialized work cannot remain silently current when coverage was blocked; see
[`outcome-loop-checkpoint-2026-10-03.md`](docs/validation/outcome-loop-checkpoint-2026-10-03.md).
The counterfactual-plan endpoint compares the selected plan with a side-effect-free projection using
deterministic evidence, cost, latency, risk, and completeness estimates; all candidates remain
non-executable read models.

Completed outcome reviews can also be projected through
`GET /v1/missions/{mission_id}/knowledge-change-proposals`. These are deterministic,
tenant-scoped suggestions with evidence and reconciliation lineage. They are review-only: they do
not write the knowledge ledger, mutate shared vocabulary, register handlers, grant permissions, or
create runtime work. Shared-taxonomy candidates always remain explicitly human-reviewable.
An explicit `POST .../materialize` stores the proposal lifecycle in the tenant-scoped
`knowledge_change_proposals` table and emits an append-only audit event. Review decisions are
recorded through `POST .../{proposal_id}/review`; accepted, rejected, superseded, and rolled-back
states remain provenance-linked and still do not apply knowledge automatically.
The only application owner is the tenant-private profile service. It requires an accepted proposal,
an active matching tenant profile, an operator-supplied structured fact, and an audit note. It writes
through `BusinessProfileRepository`; shared candidates and free-form suggestions fail closed.

Semantic selection is versioned and provenance-backed. It exposes active lattice components such as
`shared_business`, `gtm.core`, business-family domains, and industry overlays. This vocabulary guides
interpretation and job composition only; `ActionRegistry`, `TaskDispatcher`, `WorkerRuntimeService`,
tenant scope, credentials, approvals, and provider effects remain authoritative elsewhere.

The current semantic layer is intentionally bounded. Multi-parent merge semantics, tenant-private
terminology overrides, and epistemic budgets are implemented as read-only composition inputs. Budget
status and excess reasons now flow into deliverable lifecycle reconciliation; exceeded budgets remain
blocked and visible without changing runtime authority. Recurring cross-stage reconciliation remains
subsequent work; governed tenant-private application is limited to the explicit profile-service owner
described above.

---

## Quality gates

Before opening a PR, run at minimum:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python scripts/validation/graft_plus_graft1st_reconciliation_check.py
python scripts/validation/graft_plus_gate.py --base-ref origin/main --head-ref HEAD
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

For ambitious or unconventional ideas, use the separate [GRAFT+ Frontier Track](docs/development/GRAFT_PLUS_FRONTIER_TRACK.md).
It produces a side-by-side planning artifact and never grants runtime authority; promotion still requires
the standard GRAFT+ impact and proof workflow.

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
| 0034 | email_send_idempotency_receipts (SMTP send replay protection) |
| 0035 | mission_composition_proposals (durable compose history; no execution authority) |
| 0036 | interpretation thread/proposal-kind fields and tenant/actor/thread index |

**Alembic head:** `0036_composition_thread`

### Mission composition (plain language → plan)

```text
raw instruction → interpret (canonical outcomes, send_policy, quantity)
  → route jobs → resolve abilities → proposal
  → confirm → intake + plan + task graph
  → runtime queue admission (separate)
```

- Compose is read-only / declarative; incomplete input returns **full-mission restatement** requirements (not fragment Q&A merge).
- Proposals may be stored durably in `mission_composition_proposals` when a DB session is present (audit / supersession / loop escalation only).
- See [`docs/architecture/ADR-0008-mission-composition-engine.md`](docs/architecture/ADR-0008-mission-composition-engine.md).

---

## Source-of-truth docs

Start here when working on product direction and current runtime behavior.
`PROJECT_SPEC.md` is the canonical specification; `SYSTEM_ARCHITECTURE.md` is the code-aligned visual map.

- `PROJECT_SPEC.md`
- `README.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/development/GRAFT_PLUS_WORKFLOW.md`
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

## Contract audit status

**Last audited:** August 1, 2026 (`main`, Alembic head `0036_composition_thread`)

The July 2026 contract replay closed the README follow-up audit list. Authority classes below map to `docs/contracts/authority-ledger.v1.yaml` (`declarative`, `read_model`, `governed_mutation`, `runtime_authoritative`). `python scripts/validation/contract_drift_check.py` passes on `main`.

| Audit area | Status | Finding |
|---|---|---|
| Readiness dependency precision | Closed | `ReadinessEvaluatorService` pings DB + queue, fails closed with sanitized `503` reasons; health stays lightweight. Matrix: CP-06, CP-07. |
| Approved-contract replay | Closed | README inventory rows reconcile to 53 authority-ledger entries with required proof paths; route families align with `backend/api/router.py`. |
| Mission-to-runtime bridge replay | Closed | Staged bridge endpoints remain bounded per ledger (`runtime_admission_readiness_preview_contracts` through `worker_run_admission_mutation_contract`). Contract tests cover each stage; matrix EX-26–EX-31. |
| Capability/adapter enforcement boundary | Closed | Registry and adapter routes are `declarative` only; runtime execution binds through `ToolRuntimeAuthority` / `ActionRegistry`, not declaration CRUD. |
| Evidence/outcome/retrieval lifecycle | Closed | Routes persist governance records (`declarative`); they do not enqueue work or mutate execution tasks/leases. |
| Webhook reliability replay | Closed | Endpoint CRUD, encrypted signing secrets, delivery records, replay, and dispatch align with `webhook_contract` proofs. |
| SaaS/quota admission replay | Closed | `QuotaEnforcementService` and rate-limit middleware gate API usage; queue/mission/API-key admission paths have contract and unit coverage. |
| Mission approval/admission semantics | Classified | **Enforced gates:** `PolicyGuardian` → `pending_review` at queue admission; `requires_human_review` on tasks; ability-runtime launch authority; `side_effect_authorization` for external actions; informed-autonomy disclaimer (ADR-0005). **Advisory metadata:** `mission.approval_required` (stored and surfaced in Mission Brief, not enforced at queue admission); `capability.approval_requirements` (declaration validation); `outcome_review.human_approval_required` (review metadata). |
| Validation matrix freshness | Closed | AT-05 refreshed: public probes are `/health`, `/readiness`, `/v1/system/health`, `/v1/system/readiness` only; `POST /v1/operations/recovery` requires tenant auth + `RUNTIME_OPERATE` (FR-06, `test_recovery_public_contract.py`). |
| Project state report freshness | Current | `docs/PROJECT_STATE_REPORT.md` dated August 1, 2026; refresh on each release cycle per `docs/policies/DOCS_FRESHNESS_POLICY.md`. |

Remaining platform gaps (outside this audit closure):

- wire `mission.approval_required` as an optional runtime gate if product requires mission-level approval before queue admission
- opt-in plugin-lane live proof (HubSpot/Gmail/Salesforce) in staging with real tokens
- promote informed-autonomy matrix rows (AU-*) from `deferred` when `AJENDA_AUTONOMY_DISCLAIMER_MODE` is enabled in staging
