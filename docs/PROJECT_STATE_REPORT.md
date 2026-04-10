# Ajenda AI — Project State Report

**Date:** April 10, 2026
**Branch:** `main` (post-remediation: all six structural gaps resolved)
**Version:** 1.1.0 (per `pyproject.toml`)

This document provides an accurate assessment of the Ajenda AI codebase following the six-section structural remediation. It supersedes the previous report, which contained several claims that were not yet backed by code.

---

## 1. Architectural Posture & Completeness

### 1.1. Multi-Tenancy and Isolation

PostgreSQL Row-Level Security policies are defined in migration `0003_row_level_security.py`. **RLS is now activated at runtime**: `DatabaseRuntime.tenant_session_scope()` issues `SET LOCAL app.current_tenant_id = :tenant_id` at the start of every tenant-scoped DB operation, making the RLS policies effective. The `get_tenant_db_session` FastAPI dependency wraps this scope for route handlers.

The `TenantContextMiddleware` intercepts `X-Tenant-Id`, validates it against the database, and sets `request.state.tenant_id`. The middleware registration order in `main.py` is correct: Tenant middleware executes before Auth middleware (Starlette reverses registration order), so API key lookups are always scoped to the validated tenant.

### 1.2. Authentication and Authorization

`AuthContextMiddleware` supports OIDC/JWT tokens and cryptographically hashed API keys. The production runtime contract guard (`validate_runtime_contract`) blocks startup if `AJENDA_OIDC_JWKS_URI` or `AJENDA_OIDC_ISSUER` point to localhost in production mode. RBAC is enforced on `/v1/admin/*` routes. Cross-tenant rejection is verified by integration tests.

Authorization now includes a policy-as-code runway:
- `AuthorizationService.from_settings()` selects authz mode from runtime config.
- Supported modes: `rbac`, `shadow_opa`, `enforce_opa`.
- OPA adapter (`OpaPolicyDecisionPoint`) is fail-closed and supports shadow divergence auditing.
- Runtime guards validate OPA URL and timeout when OPA modes are enabled.

### 1.3. SaaS Governance and Quota Enforcement

`TenantLifecycleService` handles provisioning, suspension, reactivation, and soft-deletion. `QuotaEnforcementService` enforces plan limits (Free, Starter, Pro, Enterprise) in real-time on all mutation routes. Integration tests against real Postgres cover the full tenant lifecycle.

### 1.4. Regulatory Compliance Layer

`PolicyGuardian.evaluate_task()` reads typed domain model columns (`compliance_category`, `jurisdiction`, `requires_human_review`) — not `metadata_json`. This is the correct source of truth for compliance decisions.

`PolicyGuardian` is wired into `ExecutionCoordinator.queue_task()` as Step 2 of the queuing pipeline (after runtime governance, before enqueue). Tasks that fail the compliance check transition to `PENDING_REVIEW` (migration 0008, state machine updated) instead of being silently blocked. A `GovernanceEvent` and `AuditEvent` are emitted for every compliance hold.

Human reviewers approve (`→queued`) or reject (`→cancelled`) held tasks via the admin API.

### 1.5. Resilient Execution Runtime

**Lease recovery is now correct**: `RedisQueueAdapter.release_lease()` atomically returns the task payload to the `pending` queue using an `RPUSH` + `DEL` pipeline before deleting the lease key. Previously it only deleted the lease key, silently stranding tasks in the `processing` set.

**Retry tracking is now correct**: `ExecutionTask.retry_count` is a typed `Integer` column (migration 0008, default 0). `RuntimeMaintainer` reads and increments this column directly. Tasks are dead-lettered after `max_retries` (default: 3). Previously `retry_count` was read via `getattr(task, "retry_count", 0)` which always returned 0, making the dead-letter threshold unreachable.

### 1.6. Webhook Delivery

Webhook secrets are stored as Fernet-encrypted ciphertext (`secret_ciphertext`, migration 0009) via `WebhookSecretProtector`. At delivery time, the ciphertext is decrypted to produce the plaintext HMAC-SHA256 signing key. Tenants can now verify delivery signatures using their plaintext secret. Legacy endpoints (created before migration 0009) fall back to the bcrypt hash as the signing key.

Reliability operations are now tenant-facing:
- Replay endpoint: `POST /v1/webhooks/{endpoint_id}/deliveries/{delivery_id}/replay`
- Tenant summary endpoint: `GET /v1/webhooks/reliability/summary`
- Endpoint summary endpoint: `GET /v1/webhooks/{endpoint_id}/reliability/summary`
- Hourly reliability series is fixed-width and zero-filled for dashboard-safe charting.

### 1.7. Observability

`GET /v1/observability/metrics` returns live Prometheus text format metrics computed from real DB COUNT queries (task status counts, lease counts, worker utilization). The `PrometheusExporter` renders the snapshot. The Prometheus `ServiceMonitor` scrape path is aligned: `path: /v1/observability/metrics`. All three K8s image tags are aligned to `1.1.0`.

---

## 2. Test Matrix and Quality Assurance

| Metric | Value |
|--------|-------|
| **Unit tests passing** | 269 |
| **Failures** | 0 |
| **Ruff lint errors** | 0 |
| **Mypy type errors** | 0 |

**Coverage areas:**
- Domain models, state transitions, JWT validation, middleware logic
- Quota enforcement math, per-route rate limiting
- Compliance policy evaluation (EU AI Act, Colorado SB24-205, NYC LL144, FTC/TCPA)
- Webhook dispatch (httpx), HMAC signing, auto-disable on failure
- Production runtime contract guards (OIDC localhost, rate limit parameters)
- Integration tests: tenant lifecycle, webhook repository CRUD (real Postgres via testcontainers)
- Integration tests: middleware stack, DB session lifecycle, RBAC, cross-tenant rejection, lease recovery

---

## 3. Operational and Deployment Readiness

- `Dockerfile`: Multi-stage, production-ready image based on `python:3.12-slim`
- `docker-compose.yml`: Local development orchestration (API + Postgres 16 + Redis)
- `alembic/`: 9 migrations, current head is `0009_add_webhook_secret_ciphertext`
- `.github/workflows/`: CI pipeline with PR gate (ruff, mypy, pytest) and release workflow
- `deploy/k8s/`: Deployment manifests, ServiceMonitor, migration Job — all at version `1.1.0`
- `infra/`: Terraform modules for ECS, RDS, ElastiCache, Secrets Manager, VPC

---

## 4. Prioritized Next Actions

### Priority 1: Admin API for PENDING_REVIEW Queue (Compliance UX)

The `PENDING_REVIEW` state is now wired end-to-end, but there are no admin API endpoints to list held tasks, approve them (`→queued`), or reject them (`→cancelled`). Operators cannot act on compliance holds without direct DB access.

**Action:** Add `GET /v1/admin/review-queue` and `POST /v1/admin/tasks/{task_id}/approve|reject` endpoints with admin RBAC.

### Priority 2: Tenant-Scoped DB Session Rollout

`get_tenant_db_session` exists and activates RLS, but most existing routes still use `get_db_session`. The tenant-scoped dependency should be rolled out to all tenant-facing routes (`/v1/missions/*`, `/v1/tasks/*`, `/v1/webhooks/*`, etc.) to make RLS universally effective.

### Priority 3: Webhook Secret Key Rotation

`WebhookSecretProtector` uses a single Fernet key from `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY`. A key rotation mechanism (re-encrypt all ciphertexts with the new key) is needed for production secret hygiene.

### Priority 4: Admin Dashboard Frontend

The `/v1/admin/*` routes exist but operators need a visual interface for tenant management, quota monitoring, compliance review queue, and dead-letter inspection.
