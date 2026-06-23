# ADR-0004: Worker Tenancy Strategy

**Status:** Accepted  
**Date:** 2026-06-21

## Context

Self-serve tenants enqueue work to tenant-scoped Redis queues. The worker daemon previously polled exactly one `AJENDA_WORKER_TENANT_ID`, so arbitrary signups could not execute unless operators provisioned a worker per tenant.

## Decision

Adopt **build-time configurable worker tenancy** with two modes:

| Mode | Config | Behavior |
|------|--------|----------|
| `single` | `AJENDA_WORKER_TENANT_MODE=single` + `AJENDA_WORKER_TENANT_ID` | Legacy: one tenant queue per worker deployment |
| `multi` | `AJENDA_WORKER_TENANT_MODE=multi` | Round-robin `claim_next_task` across active tenants (`tenants.status=active`, not deleted), roster refreshed every `AJENDA_WORKER_TENANT_REFRESH_SECONDS` |

Implementation: `RoundRobinActiveTenantClaimTarget` in `backend/workers/tenant_scheduler.py`, wired from `deploy/scripts/start-worker.sh`.

Production SaaS default: **`multi`**.

## Consequences

- Self-serve signups can execute without per-tenant worker pools.
- Fairness is round-robin, not weighted by queue depth (future improvement).
- Suspended/deleted tenants are excluded automatically on roster refresh.
- Per-tenant worker deploys remain supported for enterprise isolation.

## Verification

- `tests/unit/workers/test_tenant_scheduler.py`
- `tests/unit/repositories/test_tenant_repository_active_list.py`
- `tests/unit/config/test_runtime_contract_production.py` (multi-mode production guards)
- `tests/deployment/test_docker_entrypoint_contract.py` (`build_claim_target` wiring)