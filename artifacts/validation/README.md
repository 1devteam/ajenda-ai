# Validation Artifacts

This directory stores evidence captured by the live runtime validation runner.

Primary runner files:

- `scripts/validation/live_runtime_matrix.sh`
- `scripts/validation/lib.sh`

The artifact tree is not incidental output. It is part of Ajenda’s runtime-proof and release-governance model.

---

## Purpose

Validation artifacts exist to capture the evidence needed to judge whether:

- a scenario actually executed
- the scenario result can be trusted
- the required proof surfaces were present
- the current build is safe to promote

Artifacts support scenario classification, run outcomes, and release decisions.

---

## Directory layout

Artifacts are written under:

- `artifacts/validation/<timestamp>/<scenario-id>/...`

Run-level artifacts now also include:

- `artifacts/validation/<timestamp>/scenario_results.tsv`
- `artifacts/validation/<timestamp>/summary.json`

Example:

- `artifacts/validation/20260418T000000Z/RG-06/...`

Each scenario directory may contain combinations of:

- `status.txt`
- `headers.txt`
- `body.txt`
- `run_outcome.txt`
- `evidence_status.txt`
- `notes.txt`
- `validation_env.txt`
- DB snapshots (`*.tsv`)
- Redis snapshots (`*.txt`)
- audit/governance extracts
- worker log evidence

---

## Run-level manifest files

### `scenario_results.tsv`

This is the per-run scenario ledger.

It records, for each executed scenario:

- scenario ID
- run outcome
- evidence status
- validation environment
- artifact path
- notes

This gives the run a single machine-readable ledger across scenario folders.

### `summary.json`

This is the run-level summary manifest.

It records:

- validation timestamp
- artifact directory
- validation environment
- aggregate outcome counts
- path to the scenario ledger

This gives each validation run one authoritative summary surface in addition to the per-scenario artifact directories.

---

## Evidence sources

Depending on the scenario, artifact evidence may come from:

- API responses
- database queries
- Redis queue state
- audit/governance rows
- worker log output

Critical runtime scenarios are strongest when they include multiple layers of proof rather than a single successful API response.

---

## Evidence sufficiency

Artifact capture should be evaluated explicitly.

Recommended evidence-quality semantics:

- `complete`
- `partial`
- `missing`
- `stale`

### `complete`

All required evidence surfaces for the scenario were captured.

### `partial`

Some required evidence surfaces were captured, but not all.

### `missing`

Required evidence was absent.

### `stale`

Artifacts exist, but they are not trustworthy for the current run because they are outdated or disconnected from the scenario execution being evaluated.

---

## Relationship to scenario outcomes

Scenario outcomes and artifact quality are related, but they are not the same thing.

A scenario may:

- execute and appear to succeed
- but still have incomplete or missing evidence

That means the system should distinguish:

- `run_outcome`
- `evidence_status`

This prevents weak proof from masquerading as authoritative proof.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `AJENDA_API_URL` | API base URL for validation calls |
| `AJENDA_DB_URL` | Postgres connection string for evidence queries |
| `AJENDA_REDIS_URL` | Redis URL for queue evidence |
| `AJENDA_TENANT_ID` | Tenant UUID for tenant-scoped scenarios |
| `AJENDA_AUTH_HEADER` | Auth header for protected endpoints |
| `AJENDA_LOG_SOURCE` | Worker log file path or Docker container name |
| `AJENDA_VALIDATION_ENV` | Validation environment classification (`local`, `ci`, `shared_dev`, `isolated`, `staging`) |

Optional scenario-specific IDs:

- `AJENDA_SAMPLE_TASK_ID`
- `AJENDA_FORCE_FAIL_TASK_ID`
- `AJENDA_DEAD_LETTER_TASK_ID`
- `AJENDA_PENDING_REVIEW_TASK_ID`

---

## Usage

```bash
# Run all supported scenarios
scripts/validation/live_runtime_matrix.sh

# Run read-only scenarios
scripts/validation/live_runtime_matrix.sh --group read-only

# Run tenant-scoped mutation scenarios
scripts/validation/live_runtime_matrix.sh --group tenant-mutations

# Run global mutation scenarios
scripts/validation/live_runtime_matrix.sh --group global-mutations

# Run a single scenario
scripts/validation/live_runtime_matrix.sh --scenario RG-03
```

---

## Safety classes

Ajenda’s validation model uses these safety classes:

- `SAFE_READ_ONLY`
- `TENANT_SCOPED_MUTATION`
- `GLOBAL_MUTATION`

### Operational meaning

#### `SAFE_READ_ONLY`

No mutation. Suitable for broad, repeated execution.

#### `TENANT_SCOPED_MUTATION`

Mutates one tenant’s state. Requires scoped intent and clean test data discipline.

#### `GLOBAL_MUTATION`

Can mutate broader runtime state and must run only where cross-tenant/global operational mutation is acceptable.

---

## Environment eligibility

Not every scenario is appropriate in every environment.

Recommended execution-policy distinctions include:

- CI allowed
- local allowed
- shared dev allowed
- isolated environment only
- staging only
- approval required

The artifact set should be interpreted in the context of where the scenario was run.

A scenario that should not run in the current environment should not be treated as a normal pass/fail execution result.

---

## Artifact trust model

Artifacts are trustworthy only when:

- the scenario actually executed
- the evidence is tied to the current run
- required evidence surfaces were captured
- the environment was eligible for that scenario
- the artifact set is sufficiently complete for the row being judged

This is why artifact review must distinguish:

- execution result
- evidence completeness
- environment eligibility
- static matrix maturity/backing

---

## What artifacts are for

Artifacts are meant to support:

- scenario-level runtime proof
- release-gating decisions
- operator investigation
- root-cause analysis
- validation history and auditability

They are not only debugging leftovers.

---

## Summary

Validation artifacts are part of Ajenda’s runtime-proof system.

They exist to make scenario results inspectable, evidence-backed, and usable in release judgment.
