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

## 4. SaaS-Grade Upgrade Roadmap (Integrated)

The next strategic phase aligns platform hardening with monetization leverage and enterprise saleability.

### 4.1 Tenant-Aware Adaptive Rate Limiting
- **Current state**: Static fixed-window limits.
- **Upgrade**: Add plan-aware burst credits, adaptive refill rates, and route-class weighting (e.g., expensive AI actions vs. reads).
- **Business value**: Better fairness at scale, clearer premium-tier differentiation, lower noisy-neighbor risk.
- **Implementation hooks**:
  - Extend `TenantPlan` with burst/refill parameters.
  - Introduce policy engine for `(tenant, principal, route_class)` decisions.
  - Emit limit decision telemetry for billing analytics and CS visibility.

### 4.2 Policy-as-Code Control Plane (Compliance Upsell)
- **Current state**: App-embedded compliance logic.
- **Upgrade**: Externalize authorization/compliance policy to OPA/Rego or Cedar-style policy bundles.
- **Business value**: Enterprise governance controls, auditable policy versions, shorter compliance sales cycles.
- **Implementation hooks**:
  - Add policy decision point (PDP) adapter interface.
  - Version and sign policy bundles; support dry-run mode.
  - Record decision traces in audit logs for SOC2/ISO evidence.

### 4.3 Customer Reliability Dashboard + Webhook Replay UX
- **Current state**: Internal metrics and webhook delivery tables.
- **Upgrade**: Tenant-facing SLO dashboard, per-endpoint delivery health, and one-click replay for failed webhook events.
- **Business value**: Reduced support burden, improved trust, stronger integration stickiness.
- **Implementation hooks**:
  - Publish tenant-scoped reliability aggregates (latency, success rate, retry depth).
  - Add signed replay endpoint with idempotent safeguards.
  - Surface incident timeline and actionable remediation guidance.

### 4.4 Progressive Delivery (Canary + SLO Auto-Rollback)
- **Current state**: Conventional CI gates and image publishing.
- **Upgrade**: Canary deployments with automated SLO guardrails and rollback policies.
- **Business value**: Faster safe releases, lower production incident blast radius.
- **Implementation hooks**:
  - Define release metrics contract (`error_rate`, `p95_latency`, `queue_lag`).
  - Add rollout controller integration (ECS/K8s compatible).
  - Gate promotion on objective SLO thresholds.

### 4.5 Sequencing Recommendation
1. Adaptive rate limiting (direct revenue + platform stability).
2. Reliability dashboard + webhook replay (customer-facing confidence win).
3. Progressive delivery automation (operational safety multiplier).
4. Policy-as-code control plane (enterprise compliance expansion).
