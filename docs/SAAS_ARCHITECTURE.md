# SaaS Architecture Foundation

This document defines the current SaaS architecture foundation on the rebuild line.

Ajenda is not only a SaaS wrapper around agents. The platform direction is tenant-governed autonomous execution: tenant ownership, runtime control, quota-bounded execution, compliance evidence, and validation-backed trust surfaces.

## Current foundation

The current SaaS foundation has five implemented layers:

1. Tenant domain records.
2. Tenant plan and usage contracts.
3. Tenant lifecycle service.
4. Quota enforcement service.
5. Admin control-plane routes and tenant route quota gates.

## Tenant domain

`Tenant` is the root SaaS ownership record.

Implemented tenant state fields:

- `id`
- `name`
- `slug`
- `status`
- `plan`
- `deleted_at`
- `created_at`
- `updated_at`

Implemented tenant helpers:

- `is_active()`
- `is_suspended()`
- `is_deleted()`

The active tenant contract is strict: a tenant is active only when `status == "active"` and `deleted_at is None`.

## Plan and usage contracts

`TenantPlan` defines subscription limits and feature availability.

Implemented plan limits:

- missions per month
- tasks per month
- agents per fleet
- concurrent workers
- API keys
- monthly API calls
- enabled features

`TenantUsage` stores monthly tenant counters keyed by tenant and billing period.

Implemented usage counters:

- missions created
- tasks created
- API calls
- agents provisioned
- active workers

The plan sentinel `UNLIMITED = -1` means a limit is not enforced.

## Lifecycle service

`TenantLifecycleService` owns tenant lifecycle transitions.

Implemented lifecycle operations:

- provision tenant
- suspend tenant
- reactivate tenant
- soft-delete tenant
- change tenant plan

Each lifecycle operation emits a `GovernanceEvent`. This makes tenant changes auditable instead of invisible admin state mutation.

## Quota enforcement service

`QuotaEnforcementService` is the central enforcement point for SaaS plan limits and feature gates.

Implemented checks:

- tenant is active
- mission creation quota
- task creation quota
- agent provisioning quota
- API key quota
- feature availability
- quota status lookup

Quota failures raise `QuotaExceededError` with structured fields:

- field
- limit
- current
- plan

Feature failures raise `FeatureNotAvailableError` with structured feature and plan context.

## Admin control plane

The admin API exposes cross-tenant tenant management.

Implemented admin routes:

- `POST /v1/admin/tenants`
- `POST /v1/admin/tenants/{tenant_id}/suspend`
- `POST /v1/admin/tenants/{tenant_id}/reactivate`
- `DELETE /v1/admin/tenants/{tenant_id}`
- `POST /v1/admin/tenants/{tenant_id}/plan`
- `GET /v1/admin/tenants/{tenant_id}/quota`

Admin access requires a principal with the `admin` role. These routes use the unscoped DB session because the admin control plane is cross-tenant.

## Tenant route quota gates

Tenant-facing routes enforce quota before creating new tenant-owned execution pressure.

Implemented quota-gated routes:

- API key creation checks active API key count.
- Single task queueing records one task creation.
- Mission queueing records the count of planned tasks being queued for that tenant.
- Workforce provisioning checks requested agents against the tenant plan.

These gates convert quota violations into structured HTTP 429 responses using `QUOTA_EXCEEDED` detail payloads.

## Architecture boundary

Implemented now:

- tenant ownership model
- tenant lifecycle transitions
- plan and usage tables
- quota service contracts
- admin tenant control plane
- quota gates on high-pressure tenant routes
- validation baseline for lint, unit/contract, and integration proof

Not implemented yet:

- billing provider integration
- invoices and payment state
- tenant self-service UI
- organization membership management
- per-seat billing
- webhook/event delivery foundation
- full live Redis proof unless `AJENDA_TEST_REDIS_URL` is provided

## Strategic direction

The differentiator is governed autonomous execution.

Ajenda should expose agents and runtime execution through tenant-aware controls rather than unbounded task spawning. The SaaS layer is the governance shell that lets the runtime become commercially usable:

- plans define operational limits
- usage records measure execution pressure
- quota gates stop runaway activity
- lifecycle events create evidence
- admin routes control tenant state
- validation gates prove the baseline remains clean

The next functional layer should build on this foundation by adding event delivery and webhook contracts with retry, dead-letter, tenant isolation, and auditability.
