# Ajenda AI — v1.1.0

Ajenda AI is a governed, multi-tenant execution platform built for enterprise-grade runtime control, tenant isolation, compliance-aware task admission, authoritative queue-backed execution, bounded recovery, and evidence-based release decisions.

This repository contains both the application runtime and the runtime-proof layer used to validate whether the build is promotion-worthy.

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
| **SaaS** | tenant lifecycle, plan enforcement, quota enforcement, feature gating |
| **Observability** | Prometheus metrics, audit events, governance events, validation artifacts |
| **Webhooks** | tenant-scoped outbound webhook management, reliability summaries, replay support |
| **Validation** | live runtime validation matrix, runner-backed artifact capture, release-gating scenarios |
| **Deployment** | Docker, Alembic, GitHub Actions, Kubernetes manifests |

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
2. `IdempotencyMiddleware`
3. `RateLimitMiddleware`
4. `TenantContextMiddleware`
5. `AuthContextMiddleware`
6. `RequestContextMiddleware`

Important boundary rule:

- tenant context must execute before auth resolution at runtime so API key lookups are scoped to the validated tenant

### Probe and readiness contract

Infrastructure probes remain stable at root:

- `/health`
- `/readiness`

Versioned system probes are mounted under `/v1/system`:

- `/v1/system/health`
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
  - `/v1/api-keys/*`
  - `/v1/missions/*`
  - `/v1/capabilities/*`
  - `/v1/capability-adapters/*`
  - `/v1/evidence/*`
  - `/v1/outcome-reviews/*`
  - `/v1/retrieval-contracts/*`
  - `/v1/tasks/*`
  - `/v1/workforce/*`
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

| Contract area | Current source of truth | Current behavior / authority boundary | Current proof/backing |
|---|---|---|---|
| Runtime startup | `backend/main.py`, `backend/app/config.py`, queue adapter construction | startup validates runtime configuration and queue reachability before serving | unit/config tests, deployment proof |
| Authentication modes | auth middleware, OIDC/JWT validation, API-key services and routes | supports bearer/OIDC and tenant-scoped API-key flows with fail-closed invalid credential handling and cross-tenant rejection | auth/unit/contract tests |
| Tenant/auth envelope | middleware, auth services, tenant DB dependencies, RLS migrations | tenant-scoped routes require valid tenant/auth envelope; public probes stay public | contract auth/isolation tests |
| SaaS quota and plan enforcement | tenant plan/usage models, tenant repository, quota service, task/mission/API-key routes | tenant lifecycle, feature limits, and quota checks gate platform use before unsafe over-consumption | unit/contract service and route tests |
| Queue-backed execution | `ExecutionCoordinator`, queue adapters, task routes | admitted runtime work must be represented in DB and queue authority | integration/runtime tests, live proof |
| Worker lease ownership | `WorkerRuntimeService`, `WorkerLease`, runtime transitions | worker leases control claim/start/complete/fail authority | runtime integration tests, live proof |
| Recovery reconciliation | `RuntimeMaintainer`, `QueueAdapter` recovery methods | stale work recovery uses queue evidence, expires stale leases, and avoids synthetic replacement work after payload loss | runtime recovery integration tests |
| Dead-letter inspection/retry | queue adapters, `OperationsService`, operations routes | dead-letter retry/inspection reconciles DB and queue evidence with tenant scope | contract/integration operations tests |
| Governance and audit evidence | audit/governance event models, policy path, runtime services, validation artifacts | admission, denial, completion, policy, and recovery decisions must leave reviewable evidence where required | unit/contract/integration tests, live proof |
| Compliance and policy gates | `PolicyGuardian`, mission/task compliance fields | compliance metadata and policy checks can prevent unsafe queue admission and route work to review | unit/contract tests |
| Durable mission plans | `MissionPlan`, repository, mission routes, migrations | durable mission plans are canonical over legacy mission metadata fallback | unit/API/repository/migration contract tests |
| Capability registry | capability routes, models, repositories, migrations | capabilities declare task types, schemas, required permissions/tools, risk, approval, evidence, constraints, enabled state, scope, version, and schema version; registry declarations do not execute work or bind handlers by themselves | unit/API/repository/migration contract tests |
| Capability execution adapters | adapter routes, models, repositories, migrations | adapters declare capability bindings, execution mode, input/output contracts, side-effect class, timeout/retry/idempotency expectations, and evidence expectations; adapter records do not execute work or register runtime handlers by themselves; an adapter contract is not a worker-callable runtime binding unless a separate binding/execution contract explicitly makes it so | unit/API/repository/migration contract tests |
| Task graph contracts | mission metadata normalizer and task-graph routes | task graphs are normalized metadata contracts and do not dispatch runtime work | unit/API/domain tests |
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

This proof validates a running Compose stack, root and versioned health/readiness probes, real queue-backed worker completion, released lease state, task output lineage, worker completion audit evidence, live Prometheus metrics at `/v1/observability/metrics`, Prometheus scrape-target health, and Redis lease cleanup.

---

## Local development

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Install project in editable mode
pip install -e ".[dev]"

# 3. Start infrastructure
docker compose up -d

# 4. Run migrations
alembic upgrade head

# 5. Start the API
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
- webhook reliability and replay support
- live runtime validation artifacts and release-gating structure
- deployment runtime proof with Prometheus and OpenTelemetry collector coverage

---

## Current hardening focus

The current top priority is not random feature growth.

The current hardening focus is:

- keeping README, architecture docs, validation docs, tests, and implementation aligned
- preserving authoritative runtime proof for recovery, dead-letter, and lease-bound execution paths
- expanding high-value resilience and isolation scenarios without weakening existing release gates
- tightening release confidence around real runtime evidence rather than doc-only posture

Recent hardening work already merged on `main` includes:

- protected recovery endpoint and admin-only global recovery control-plane access
- runtime queue reconciliation and dead-letter truth hardening
- retrieval/API-key/compliance/quota/dead-letter contract-schema parity audit
- mission-plan status hardening through migration constraints
- deployment/runtime contract hardening for canonical `AJENDA_*` env aliases, Compose env-file behavior, worker entrypoint alignment, probe/metrics paths, Prometheus scrape health, and OpenTelemetry collector inclusion in the live proof stack
- local proof against `main` commit `53b4ee4` additionally validated full non-integration tests, full integration tests, targeted runtime recovery tests, live-runtime-proof, lint/format/type checks, and Compose Alembic head `0019_harden_retrieval_values`; future commits must rerun applicable gates instead of treating this proof as evergreen

---

## Quality gates

Before opening a PR, run at minimum:

```bash
ruff check .
ruff format --check .
python -m pytest -m "not integration"
```

Run integration and validation flows when your change affects runtime behavior, queueing, recovery, isolation, release-gating, or validation semantics.

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

---

## Source-of-truth docs

Start here when working on product direction and current runtime behavior:

- `README.md`
- `PROJECT_SPEC.md`
- `docs/product/mission-based-ai-core.md`
- `docs/deployment/production-env-contract.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`
- `artifacts/validation/README.md`
- `docs/PROJECT_STATE_REPORT.md`
- `docs/SAAS_ARCHITECTURE.md`

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
- project state report freshness: reconcile older deployment-surface wording, including any Terraform/ECS references, with the current repository snapshot before using that document as authoritative prompt context
