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
| **Deployment** | Docker, Alembic, GitHub Actions, Terraform, Kubernetes manifests |

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
- prod-like live runtime proof for health/readiness, worker execution, observability metrics, audit/lineage evidence, and Redis lease cleanup
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

This proof validates a running Compose stack, root and versioned health/readiness probes, real queue-backed worker completion, released lease state, task output lineage, worker completion audit evidence, live Prometheus metrics at `/v1/observability/metrics`, and Redis lease cleanup.

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
- tenant-scoped mutations change one tenant’s state and require scoped care
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
- quota and SaaS lifecycle support
- webhook reliability and replay support
- live runtime validation artifacts and release-gating structure

---

## Current hardening focus

The current top priority is not random feature growth.

The current hardening focus is:

- keeping README, architecture docs, validation docs, tests, and implementation aligned
- preserving authoritative runtime proof for recovery, dead-letter, and lease-bound execution paths
- expanding high-value resilience and isolation scenarios without weakening existing release gates
- tightening release confidence around real runtime evidence rather than doc-only posture

Recent hardening work already merged on `main` includes:

- recovery route visibility for `dead_lettered_count`
- targeted recovery-hardening verification workflow coverage
- runtime and queue hardening for bounded stale-lease recovery paths
- integration and contract coverage expansion across recovery and dead-letter behavior

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
| 0002 | Execution branches |
| 0003 | Row-Level Security policies |
| 0004 | Recovering state + worker leases |
| 0005 | Compliance columns on execution tasks |
| 0006 | SaaS tenant lifecycle |
| 0007 | Webhook endpoints and deliveries |
| 0008 | retry_count + pending_review state |
| 0009 | Webhook secret ciphertext |

---

## Source-of-truth docs

Start here when working on product direction and current runtime behavior:

- `docs/product/mission-based-ai-core.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`
- `artifacts/validation/README.md`
- `docs/PROJECT_STATE_REPORT.md`
- `docs/SAAS_ARCHITECTURE.md`
