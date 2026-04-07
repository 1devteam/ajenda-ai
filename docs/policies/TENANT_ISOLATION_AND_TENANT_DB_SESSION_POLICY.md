# Ajenda AI — Tenant Isolation and `tenant_db_session` Policy

## Status

**Authoritative engineering policy — in effect as of v1.1.0**

This document defines the mandatory isolation model for Ajenda AI's multi-tenant SaaS runtime. It is written for the current Ajenda AI architecture:

- shared application runtime
- shared PostgreSQL database
- tenant-owned rows in shared tables
- PostgreSQL Row-Level Security as a defense-in-depth boundary
- tenant-aware middleware
- request-scoped SQLAlchemy sessions

This is not optional guidance. This policy is the default rule set for all new and existing tenant-facing code.

---

## 1. Policy objective

Ajenda AI must enforce tenant isolation at **all** of these layers:

1. request ingestion
2. authentication and authorization
3. database session creation
4. query execution
5. repository access
6. background execution
7. queue/cache/storage naming
8. audit and observability

A request that is logically tenant-scoped must never execute against a cross-tenant database session by accident. The system must fail closed.

---

## 2. Core architectural decision

Ajenda AI adopts this tenant isolation model:

- **HTTP layer** — tenant context is established by middleware before tenant-facing business logic runs; tenant context is bound to the authenticated principal; cross-tenant mismatches are rejected before handlers execute
- **DB layer** — all tenant-facing route handlers use a tenant-scoped DB dependency; the tenant-scoped dependency sets PostgreSQL tenant session context for the current transaction; PostgreSQL RLS is treated as a defense-in-depth isolation boundary, not the only boundary
- **Data-access layer** — tenant-facing repositories and services must remain tenant-scoped; primary-key-only access is forbidden for tenant-facing reads/writes unless the access path is protected by RLS and the method is explicitly documented as tenant-safe
- **Admin layer** — cross-tenant access is allowed only on explicitly designated admin/control-plane paths; cross-tenant access always requires explicit authorization and audit logging; admin/cross-tenant DB sessions must be intentionally selected, never the default

---

## 3. Definitions

### 3.1 Tenant-facing route

A route is tenant-facing if it reads, writes, queues, mutates, lists, or inspects any tenant-owned resource. For Ajenda AI, tenant-facing routes include, at minimum:

- `/v1/api-keys/*`
- `/v1/missions/*`
- `/v1/tasks/*`
- `/v1/workforce/*`
- `/v1/branches/*`
- `/v1/runtime/*` when acting on tenant-owned runtime data
- `/v1/operations/*` when acting on tenant-owned work
- `/v1/system/*` when returning tenant-owned operational state
- `/v1/webhooks/*`

### 3.2 Public route

A route is public if it is infrastructure-facing or bootstrap-facing and does not access tenant-owned business data. Examples:

- `/health`
- `/readiness`
- `/metrics`
- `/docs`
- `/openapi.json`
- `/redoc`
- `/v1/auth/*`

### 3.3 Cross-tenant/admin route

A route is cross-tenant/admin if it is explicitly designed to inspect or control multiple tenants. Examples:

- `/v1/admin/*`
- internal diagnostic/admin operations explicitly marked as cross-tenant

---

## 4. Mandatory session rule

### 4.1 Default rule

**All tenant-facing routes MUST use `get_tenant_db_session`.**

### 4.2 Exception rule

`get_db_session` may be used only for:

- public routes (health, readiness, metrics)
- auth bootstrap flows that do not operate on tenant business data
- explicitly designated admin/cross-tenant routes
- startup/shutdown/runtime boot logic outside route handling

### 4.3 Prohibited default

No tenant-facing route may use `get_db_session` as its handler-level DB dependency. This is a hard policy violation.

---

## 5. Mandatory tenant context rule

### 5.1 Source of truth

For tenant-facing request handling, the authoritative in-process tenant context is:

- `request.state.tenant_id`
- `request.state.tenant`
- `request.state.principal`

### 5.2 Route handlers must not trust raw header input

Tenant-facing route handlers must **not** treat `X-Tenant-Id` as an authoritative value merely because it was supplied by the client. The route handler must use:

- `request.state.tenant_id`, or
- a dependency that reads `request.state.tenant_id`

### 5.3 Prohibited pattern

This is forbidden in tenant-facing handlers:

```python
# FORBIDDEN
tenant_id: str = Header(alias="X-Tenant-Id")
db: Session = Depends(get_db_session)
```

Reason:

- it duplicates tenant context sourcing inside the handler
- it normalizes header trust as an application pattern
- it weakens the "middleware establishes tenant context" contract
- it increases the chance of using a non-tenant-scoped session with a tenant header

---

## 6. Approved dependency model

The approved dependency model for tenant-facing handlers is:

```python
db: Session = Depends(get_tenant_db_session)
tenant_id: uuid.UUID = Depends(get_request_tenant_id)
```

Where:

- `get_request_tenant_id` returns `request.state.tenant_id` as a `uuid.UUID`
- `get_tenant_db_session` opens a transaction-scoped DB session and sets tenant session context for PostgreSQL RLS
- neither dependency trusts raw request headers as business truth

> **Note on type:** The policy document uses `str` in examples for readability. The Ajenda AI implementation types `tenant_id` as `uuid.UUID` throughout the domain model. `get_request_tenant_id` returns `uuid.UUID` and performs the cast at the dependency boundary.

### 6.1 Required helper

Ajenda AI exposes a single canonical dependency:

```python
def get_request_tenant_id(request: Request) -> uuid.UUID:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context on request state.")
    return uuid.UUID(str(tenant_id))
```

This helper is the only approved way for handlers to receive tenant ID.

---

## 7. Middleware policy

### 7.1 Tenant middleware

Tenant middleware must:

- run before tenant-dependent business logic
- validate `X-Tenant-Id`
- normalize and attach tenant context to request state
- reject unknown, suspended, or deleted tenants
- fail closed if DB-backed tenant validation is unavailable

### 7.2 Auth middleware

Auth middleware must:

- authenticate the request
- bind principal context to the request
- reject cross-tenant mismatches between principal tenant and request tenant
- never silently downgrade to anonymous behavior for tenant-facing routes

### 7.3 Order rule

Tenant extraction and tenant availability checks must happen before any handler logic that depends on tenant context. Cross-tenant principal rejection must happen before the route handler executes.

> **Implementation note:** Starlette applies middleware in reverse registration order. In `main.py`, Auth middleware is registered before Tenant middleware so that Tenant middleware executes first at request time.

---

## 8. Database session policy

### 8.1 Tenant session contract

`get_tenant_db_session` must:

- open a transactional SQLAlchemy session
- set PostgreSQL tenant session context using `SET LOCAL app.current_tenant_id`
- ensure the tenant context is scoped to the current transaction
- close and clean up after the request completes

### 8.2 Required Postgres behavior

Tenant session context must be set with the transaction-scoped pattern:

```sql
SET LOCAL app.current_tenant_id = '<tenant_uuid>';
```

This is implemented in `DatabaseRuntime.tenant_session_scope()`.

### 8.3 Admin session contract

`get_db_session` is a cross-tenant-capable session and therefore must be treated as privileged. It is never the default choice for tenant-facing request handling.

---

## 9. Repository and service policy

### 9.1 Repository rule

Tenant-facing repository methods must be one of the following:

1. **explicitly tenant-scoped** — e.g., `get_for_tenant(resource_id, tenant_id)`, `list_for_tenant(tenant_id)`
2. **documented as RLS-backed and safe under tenant session context** — only when the route/service path is guaranteed to use `get_tenant_db_session`

### 9.2 Forbidden repository pattern

This is forbidden in tenant-facing call paths:

- `repo.get(id)` with no tenant scope and no documented RLS guarantee
- direct session queries in handlers with no tenant-aware repository method
- cross-tenant list queries from tenant-facing routes

### 9.3 Service rule

Services called from tenant-facing routes must either:

- accept `tenant_id` explicitly and enforce it, or
- be documented as safe only under `get_tenant_db_session`

---

## 10. Queue, cache, storage, and logging policy

### 10.1 Queue keys

All queue keys must include tenant identity where the queue surface is tenant-scoped.

### 10.2 Cache keys

All cache keys for tenant-owned data must be tenant-prefixed.

### 10.3 Storage paths

All blob/file/object storage paths must be tenant-prefixed or tenant-partitioned.

### 10.4 Logs and audit

Every tenant-facing action must log:

- tenant_id
- request_id
- actor identity where present
- operation outcome

Secrets must never be logged.

---

## 11. Worker and background-job policy

### 11.1 Worker rule

Background workers operating on tenant-owned rows must open DB sessions via the tenant session model for the task's tenant.

### 11.2 Control-loop exception

Global runtime loops may use a cross-tenant session only for:

- scanning global control tables
- identifying lease expiry candidates
- reading control-plane state

Once a worker begins processing a tenant-owned resource, it must switch into tenant-scoped session behavior for the tenant-owned data access path.

### 11.3 No hidden cross-tenant service calls

A worker may not fetch or mutate tenant-owned rows through a globally scoped session just because the code is "internal."

---

## 12. Route classification for current repo

### 12.1 Must use `get_tenant_db_session`

| Route module | Reason |
|---|---|
| `backend/api/routes/api_keys.py` | Tenant-owned API keys |
| `backend/api/routes/mission.py` | Tenant-owned missions |
| `backend/api/routes/task.py` | Tenant-owned tasks |
| `backend/api/routes/webhooks.py` | Tenant-owned webhook endpoints and deliveries |
| `backend/api/routes/workforce.py` | Tenant-owned agents |
| `backend/api/routes/branch.py` | Tenant-owned execution branches |
| `backend/api/routes/operations.py` | Tenant-owned work operations |
| `backend/api/routes/system.py` (tenant status endpoint) | Returns tenant-owned operational state |

### 12.2 Must use `get_db_session`

| Route module | Reason |
|---|---|
| `backend/api/routes/health.py` | Infrastructure health — no tenant data |
| `backend/api/routes/observability.py` | Metrics — cross-tenant aggregate counts |
| `backend/api/routes/auth.py` | Auth bootstrap — no tenant business data |
| `backend/api/routes/admin.py` | Explicitly cross-tenant control plane |
| `backend/api/routes/runtime.py` | Returns global runtime mode, not tenant data |

---

## 13. Required code-review checks

A PR touching tenant-facing code must be rejected if any of the following are present:

- tenant-facing route uses `Depends(get_db_session)`
- tenant-facing route uses `Header(alias="X-Tenant-Id")` as business truth
- handler reads tenant-owned data without tenant scoping or documented RLS protection
- repository method introduces unscoped lookup in a tenant path
- cache/queue/storage key omits tenant context
- new admin/cross-tenant path is introduced without explicit audit logging
- test coverage does not include at least one negative cross-tenant case

---

## 14. Required tests

### 14.1 Mandatory route tests

Every tenant-facing route must have tests for:

- missing tenant context rejection
- invalid tenant rejection
- suspended/deleted tenant rejection where applicable
- cross-tenant principal mismatch rejection
- positive same-tenant success path

### 14.2 Mandatory data tests

At least one test per tenant-owned domain surface must verify that:

- another tenant cannot read the resource
- another tenant cannot mutate the resource
- unscoped repository access is not reachable from the tenant-facing route path

### 14.3 Mandatory admin tests

Admin routes must prove:

- cross-tenant access is possible only with admin authorization
- admin operations are audited
- non-admin principals cannot use the cross-tenant path

---

## 15. Migration policy for current repo

For Ajenda AI's current codebase, the remediation order is:

1. Replace `get_db_session` with `get_tenant_db_session` in all tenant-facing routes.
2. Remove direct `Header(alias="X-Tenant-Id")` usage from tenant-facing handlers.
3. Introduce and standardize `get_request_tenant_id`.
4. Audit repositories used by tenant-facing routes for unscoped access methods.
5. Add negative cross-tenant tests for every touched route.
6. Keep `get_db_session` only on documented public/admin/cross-tenant paths.

---

## 16. Non-negotiable rules

- Tenant-facing route = tenant-scoped session, always.
- Raw tenant header is not business truth.
- Admin/cross-tenant access must be explicit, rare, and audited.
- RLS is defense in depth, not an excuse for sloppy handler or repository code.
- Any ambiguity defaults to the safer rule: use tenant-scoped session.

---

## 17. Approval standard

This policy is considered implemented only when:

- all tenant-facing routes use `get_tenant_db_session`
- all tenant-facing routes source tenant ID from request state or a request-state dependency
- admin exceptions are explicitly documented
- route, service, and repository tests prove negative cross-tenant behavior
- code review checklists enforce the rule going forward
