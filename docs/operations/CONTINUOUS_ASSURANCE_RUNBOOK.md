# Continuous Assurance Runbook

## Purpose

The continuous-assurance process independently re-reads tenant mission/runtime truth and appends a
tenant-scoped assurance snapshot. It is a monitor, not a runtime authority owner.

It may write only:

- `assurance_snapshots` — tenant-scoped append-only observation history;
- `assurance_metric_state` — aggregate operational counters with no tenant identity.

It must not create, queue, claim, start, retry, cancel, or complete tasks; mutate missions, leases,
business profiles, knowledge, credentials, approvals, providers, or side effects; or promote
execution authority.

## Recurrence

The `assurance` service runs `python -m backend.workers.assurance_loop` independently of the
runtime worker. The default interval is 300 seconds and is configured by
`AJENDA_ASSURANCE_INTERVAL_SECONDS` with a minimum of 30 seconds.

## Observation chain

For each active tenant and mission, the assurance service reads:

`mission → tasks → queue/lease evidence → lineage → evidence → artifacts → deliverable runtime state`

It then records:

- assurance status: `aligned | incomplete | drifted | contradictory`;
- durable finding list;
- first-divergence marker;
- runtime node/edge/task-flow/record-flow counts;
- shadow/runtime reconciliation state;
- semantic reconciliation state;
- epistemic confidence when present;
- calibration eligibility and whether the observed outcome aligned.

Calibration observations are evidence samples only. They do not rewrite epistemic policy confidence. Unchanged mission observations are fingerprinted and not appended again, preventing recurring scans from biasing calibration history.

## Operator surfaces

Tenant-scoped read APIs:

- `GET /v1/observability/assurance/history`
- `GET /v1/observability/assurance/summary`

Prometheus metrics:

- `ajenda_assurance_snapshot_count`
- `ajenda_assurance_incomplete_count`
- `ajenda_assurance_drifted_count`
- `ajenda_assurance_contradictory_count`
- `ajenda_assurance_first_divergence_count`
- `ajenda_assurance_calibration_sample_count`
- `ajenda_assurance_calibration_aligned_count`
- `ajenda_assurance_scan_failure_count`

Alerts:

- `AjendaAssuranceTenantScanFailures` — critical;
- `AjendaAssuranceContradictionsPresent` — critical;
- `AjendaAssuranceDriftPresent` — warning;
- `AjendaAssuranceFirstDivergencePresent` — warning.

## Response

For `contradictory`:

1. Read the latest tenant assurance history.
2. Inspect `first_divergence`, findings, runtime summary, and reconciliation summary.
3. Inspect the mission runtime-evidence and deliverable-runtime-state read models.
4. Do not repair by editing assurance rows.
5. Repair the owning runtime/product contract, rerun the mission or reconciliation proof as
   appropriate, and confirm a later assurance snapshot returns aligned.

For `drifted`:

1. Determine whether the drift is historical missing lineage, semantic drift, stale evidence, or a
   newly introduced implementation discrepancy.
2. Preserve the prior snapshot as history.
3. Fix only the owning source; never let the monitor synthesize authority or evidence.

## Failure behavior

A tenant assurance failure is logged and does not stop other tenants from being assessed. A metrics
publication failure does not mutate runtime state. The next interval retries observation naturally.

The assurance process must remain independently stoppable. Stopping it affects monitoring freshness,
not mission execution.
