# Ajenda AI — SaaS Structural Enforcement Architecture

This document defines the production-grade SaaS enforcement boundaries for the Ajenda AI governed runtime. It ensures absolute tenant isolation, subscription tier enforcement, and usage metering across all layers of the system.

## 1. Tenant Isolation Boundaries

### 1.1 Database Layer (PostgreSQL RLS)
- **Mechanism**: PostgreSQL Row-Level Security (RLS).
- **Enforcement**: `app.current_tenant_id` session variable is set immediately upon connection checkout via SQLAlchemy events.
- **Fail-Closed**: If the variable is unset, the RLS policy evaluates to `false` and returns 0 rows.
- **Admin Bypass**: The `ajenda_admin` role bypasses RLS for system-wide operations (migrations, global metrics).

### 1.2 API Layer (Middleware)
- **Mechanism**: `TenantContextMiddleware`.
- **Enforcement**: Extracts `X-Tenant-Id` header (or from JWT claims). Validates it against the authenticated principal.
- **Cross-Tenant Rejection**: If a user authenticated as Tenant A attempts to pass `X-Tenant-Id: Tenant B`, the request is rejected with HTTP 403 Forbidden before reaching any route logic.

### 1.3 Service & Repository Layer
- **Mechanism**: Explicit `tenant_id` parameters on all repository methods.
- **Enforcement**: Repositories append `AND tenant_id = :tenant_id` to all queries, acting as a secondary defense-in-depth measure above RLS.

### 1.4 Queue & Worker Layer
- **Mechanism**: Tenant-partitioned queues or explicit `tenant_id` payload fields.
- **Enforcement**: Workers assert the `tenant_id` of the claimed task matches the context they are operating under.

## 2. Subscription & Plan Enforcement

### 2.1 Domain Models
- `TenantPlan`: Defines limits (e.g., `max_agents`, `max_tasks_per_month`, `features_enabled`).
- `TenantUsage`: Tracks current consumption.

### 2.2 Quota Middleware / Interceptors
- **Mechanism**: `QuotaEnforcementService` injected into mutation routes (e.g., `POST /tasks`, `POST /workforces/provision`).
- **Enforcement**: Checks `TenantUsage` against `TenantPlan`. Rejects with HTTP 402 Payment Required if limits are exceeded.

## 3. Tenant Lifecycle Management

### 3.1 States
- `ACTIVE`: Normal operation.
- `SUSPENDED`: Read-only access, queue consumption paused, API mutations rejected (HTTP 403).
- `DELETED`: Soft-deleted, data retained for compliance period, all access revoked.

### 3.2 Control Plane
- Internal admin routes (`/admin/tenants`) to manage lifecycle, plans, and overrides.
