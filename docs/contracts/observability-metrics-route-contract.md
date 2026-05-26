# Observability Metrics Route Contract (Bundle 4.3)

## Scope

This document defines the route-level contract for observability read surfaces introduced/confirmed in Bundle 4.3.

- `GET /v1/observability/metrics`
- `GET /v1/observability/reliability/summary`

Authority class posture follows `docs/contracts/authority-ledger.v1.yaml` and remains read-only for these surfaces.

## Route: `GET /v1/observability/metrics`

- **Authority class:** `read_model`
- **Side effects:** none
- **Auth/Tenant envelope:** public (no tenant header required, no auth required)
- **Response contract:**
  - HTTP `200`
  - `content-type` includes `text/plain`
  - Prometheus text exposition payload contains Ajenda metric families (for example `ajenda_tasks_queued`)
  - Economic observability schema includes additive, observe-only stage budget families:
    - `ajenda_stage_budget_limit{stage,budget_kind}` (gauge)
    - `ajenda_stage_budget_spend{stage,budget_kind}` (gauge)
    - `ajenda_stage_budget_breach_total{stage,budget_kind}` (counter)
- **Failure posture:** fail-safe scrape response with `200` and minimal safe metric text (`ajenda_up 0`) when collection fails.

## Route: `GET /v1/observability/reliability/summary`

- **Authority class:** `read_model`
- **Side effects:** none
- **Auth/Tenant envelope:** protected tenant route
  - missing `X-Tenant-Id` → `400`
  - missing auth credentials → `401`
  - cross-tenant principal vs request mismatch → `403`
- **Response schema (200):**
  - top-level metadata:
    - `authority_class: "read_model"`
    - `side_effect_class: "none"`
    - `does_not_execute_runtime_work: true`
  - throughput and rates are bounded numeric values
  - nested `lease_health` and `recovery` objects are present
  - schema is strict (`extra=forbid`) and should reject unknown fields in model-level validation.

## Required proof surfaces

- Contract tests:
  - `tests/contract/metrics/test_metrics_route_access.py`
  - `tests/contract/api/test_observability_routes_contract.py`
- Existing route implementation:
  - `backend/api/routes/observability.py`
- Validation context:
  - `docs/validation/live-runtime-matrix.md` (`RG-03` metrics route exposure)
