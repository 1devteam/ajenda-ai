# Ajenda AI Live Runtime Validation Matrix

## Purpose

This matrix is the source-controlled runtime validation contract for Ajenda AI.

It exists to turn architecture and runtime intent into explicit validation rows with evidence requirements and release-governance meaning.

The matrix should answer:

- what must always work
- what must never happen
- what evidence is required to trust a scenario result
- which scenarios are promotion-blocking
- which broader scenarios are implemented, partial, documented, or deferred

This document defines the static truth of the matrix.
Dynamic execution results belong to validation runs and artifacts.

---

## Product-purpose framing

Ajenda AI is a governed, multi-tenant execution platform.

Its runtime responsibilities include:

- accepting tenant-scoped work safely
- enforcing auth, tenant, policy, and compliance boundaries
- moving work through authoritative queue/state/lease transitions
- recovering safely from worker/runtime failure
- preserving tenant isolation, integrity, and auditability
- supporting release decisions based on runtime evidence

This matrix is not just a list of tests.
It is the runtime-proof and release-governance layer for those guarantees.

---

## Matrix model

### Static matrix truth

Each scenario row carries static matrix metadata that should change only when the repository truth changes.

Required static fields:

- `id`
- `domain`
- `scenario`
- `priority`
- `safety_class`
- `matrix_status`
- `validation_backing`
- `preconditions`
- `action`
- `expected_result`
- `forbidden_result`
- `evidence_sources`
- `implementation_mapping`
- `execution_policy`

### Dynamic run truth

Dynamic run values belong to a specific validation execution and should be recorded in the generated artifact/report layer.

Dynamic fields:

- `run_outcome`
- `evidence_status`
- `artifact_path`
- `notes`
- `validation_env`

Current runner-generated dynamic artifact surfaces include:

- per-scenario files:
  - `run_outcome.txt`
  - `evidence_status.txt`
  - `notes.txt`
  - `validation_env.txt`
- run-level files:
  - `scenario_results.tsv`
  - `summary.json`

This keeps dynamic run truth inspectable at both the scenario level and the whole-run level.

---

## Matrix semantics

### `matrix_status`

Allowed values:

- `documented`
- `partial`
- `implemented`
- `evidence_backed`
- `authoritative_gate`
- `deferred`

Definitions:

- `documented` — row exists in documentation but lacks strong proof backing
- `partial` — some grounding exists, but proof or mapping remains incomplete
- `implemented` — scenario maps cleanly to real implementation, but proof rigor is still limited
- `evidence_backed` — scenario has meaningful runtime/test/runner proof surfaces
- `authoritative_gate` — row is a formal release gate with strong proof backing
- `deferred` — row belongs in the matrix but is not yet closed or fully implemented

### `validation_backing`

Allowed values:

- `docs_only`
- `runner_only`
- `contract_test`
- `integration_test`
- `runner_and_contract`
- `runner_and_integration`
- `contract_and_integration`
- `runner_contract_integration`
- `manual_only`
- `unsupported`

Definitions:

- `docs_only` — described, but not strongly runnable/test-backed
- `runner_only` — backed by the validation runner
- `contract_test` — backed by contract tests
- `integration_test` — backed by integration tests
- `runner_and_contract` — backed by runner and contract tests
- `runner_and_integration` — backed by runner and integration tests
- `contract_and_integration` — backed by tests but not runner
- `runner_contract_integration` — strongest routine backing
- `manual_only` — currently depends on operator-driven execution
- `unsupported` — row exists, but current tooling does not yet support it

### `run_outcome`

Allowed values for a specific execution:

- `pass`
- `fail`
- `warn`
- `skip`
- `blocked`
- `invalid_run`
- `environment_ineligible`
- `evidence_incomplete`
- `not_executed`

### `evidence_status`

Allowed values for a specific execution:

- `complete`
- `partial`
- `missing`
- `stale`

---

## Release-decision semantics

### `pass`

Scenario executed and satisfied required expectations.

### `fail`

Scenario executed and violated required expectations.

### `warn`

Scenario did not fail outright, but produced a noteworthy condition that should influence review.

### `skip`

Scenario was intentionally not run in the current execution set.

### `blocked`

Scenario could not run because a prerequisite failed.

### `invalid_run`

Scenario execution or invocation was invalid enough that the result should not be interpreted as normal pass/fail evidence.

### `environment_ineligible`

Scenario is not appropriate for the environment in which the run was attempted.

### `evidence_incomplete`

Scenario executed, but the artifact set is too weak to trust the result as a normal pass/fail classification.

### `not_executed`

Scenario exists in the matrix but was not part of the current run.

---

## Safety classes

- `SAFE_READ_ONLY`
- `TENANT_SCOPED_MUTATION`
- `GLOBAL_MUTATION`

---

## Execution policy by safety class

These are current governance expectations for where scenarios should run. They describe current recommended policy; they are not all automatically enforced by tooling.

### `SAFE_READ_ONLY`

Recommended policy:

- CI allowed
- local allowed
- shared dev allowed
- repeated execution acceptable

### `TENANT_SCOPED_MUTATION`

Recommended policy:

- local allowed
- isolated/shared dev only when test data and tenant scope are deliberate
- seed data may be required
- cleanup/review may be required after execution

### `GLOBAL_MUTATION`

Recommended policy:

- isolated environment only
- approval strongly recommended
- not suitable for casual shared-environment use
- environment eligibility must be checked before interpreting results

Current runner behavior:

- global-mutation scenarios are gated by `AJENDA_VALIDATION_ENV`
- current allowed environments for those scenarios are `isolated` and `staging`

---

## Validation methods

- `contract-test`
- `integration-test`
- `runner`

---

## Release-gating scenarios

Release gates are promotion-blocking rows. They should remain compact and strict.

Current release-gating set: `RG-01` through `RG-12`

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RG-01 | control_plane | root health/readiness public | P1 | SAFE_READ_ONLY | authoritative_gate | contract_test | app reachable | GET `/health`, GET `/readiness` | both return 200 | public probes blocked | API | `backend/api/routes/health.py`, `tests/contract/api/test_release_gating_routes.py` | CI/local/shared_dev |
| RG-02 | control_plane | system probes public; system status envelope strict | P1 | SAFE_READ_ONLY | authoritative_gate | runner_and_contract | app reachable; tenant/auth available for protected branch when applicable | GET `/v1/system/health`, `/v1/system/readiness`, `/v1/system/status` under valid and invalid envelopes | public probes succeed; invalid protected envelope rejected | protected status exposed without required envelope | API | `backend/api/routes/system.py`, middleware, runner RG-02, contract tests | CI/local/shared_dev |
| RG-03 | operational_plane | metrics route exposed correctly | P1 | SAFE_READ_ONLY | authoritative_gate | contract_test | app reachable | GET `/v1/observability/metrics` | 200 with Prometheus text | metrics route blocked or non-Prometheus output | API | `backend/api/routes/observability.py`, metrics contract test | CI/local/shared_dev |
| RG-04 | execution_plane | queue admission succeeds for valid tenant-scoped task | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | valid auth, tenant, queue-admissible task | POST `/v1/tasks/{task_id}/queue` | task queued and evidenced in DB/audit/Redis | enqueue without authoritative queued state or tenant mismatch | API, DB, Redis, audit | `backend/api/routes/task.py`, `backend/services/execution_coordinator.py`, integration + runner RG-04 | local/isolated/shared_dev with care |
| RG-05 | auth_tenant_envelope | invalid or missing envelope is rejected without side effects | P0 | SAFE_READ_ONLY | authoritative_gate | contract_test | tenant-scoped route available | invoke protected routes with missing/invalid tenant/auth | request rejected with no mutation | mutation or enqueue on invalid envelope | API | `backend/middleware/tenant_context.py`, `backend/middleware/auth_context.py`, tenant isolation contract tests | CI/local/shared_dev |
| RG-06 | execution_plane | queued task completes cleanly | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | valid queued task and worker path | exercise worker completion path | task reaches completed, lease released, audit/log evidence present | duplicate completion, stuck processing, missing release path | DB, Redis, audit, logs | `backend/services/worker_runtime_service.py`, runtime integration + runner RG-06 | local/isolated/shared_dev with care |
| RG-07 | failure_plane | forced failure reaches valid failure terminal path | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | deterministic fail task available | exercise failure path | task enters `failed` or valid dead-letter terminal state with evidence | silent failure, missing audit, invalid terminal path | DB, Redis, audit, logs | worker runtime + dispatcher + runner RG-07 | local/isolated/shared_dev with care |
| RG-08 | recovery_plane | stale claimed lease recovery re-queues safely | P1 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | expired claimed lease exists | POST `/v1/operations/recovery` | claimed task re-queued and lease expired | no-op on expired claimed work; unsafe mutation patterns | API, DB, audit | `backend/services/runtime_maintainer.py`, recovery integration + runner RG-08 | isolated_env_only |
| RG-09 | recovery_plane | stale running lease recovery and retry/dead-letter path | P1 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | expired active lease exists | POST `/v1/operations/recovery` | running work recovers to queued or dead-lettered according to retry state | stuck running work; illegal retry behavior | API, DB, audit, Redis | `backend/services/runtime_maintainer.py`, recovery integration + runner RG-09 | isolated_env_only |
| RG-10 | dead_letter_plane | illegal dead-letter retry is rejected safely | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | contract_and_integration | task not in legal retry state | POST dead-letter retry route | illegal retry rejected, no mutation | illegal requeue or state change | API, DB | dead-letter operation contract + integration tests | local/isolated/shared_dev with care |
| RG-11 | recovery_plane | recovery mutates only stale work | P0 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | recovery endpoint available; healthy work exists | POST `/v1/operations/recovery` and inspect before/after | only expired/stale work changes | healthy work mutation or drift | API, DB, audit | recovery service + runner RG-11 | isolated_env_only |
| RG-12 | compliance_plane | policy denial routes task to pending review with no enqueue | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | policy-denied task available | POST `/v1/tasks/{task_id}/queue` | 400 denial, pending_review/gov evidence, no enqueue | unsafe queue admission after policy denial | API, DB, Redis, audit, governance | execution coordinator + policy path + runner RG-12 | local/isolated/shared_dev with care |

---

## Broader runtime scenarios

Broader matrix rows expand operational truth beyond release gates. They are important even when they are not promotion-blocking.

Current broader scenario count: **29**

### Control plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CP-01 | control_plane | root liveness public | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET `/health` | 200 | public liveness blocked | API | health route contract | CI/local/shared_dev |
| CP-02 | control_plane | root readiness validates runtime readiness path | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET `/readiness` | 200 when readiness is healthy | readiness exposed as meaningless success | API | health/readiness contract | CI/local/shared_dev |
| CP-03 | control_plane | system health route public | P2 | SAFE_READ_ONLY | evidence_backed | runner_and_contract | app reachable | GET `/v1/system/health` | 200 | public route unexpectedly protected | API | system route contract | CI/local/shared_dev |
| CP-04 | control_plane | system readiness route public | P2 | SAFE_READ_ONLY | evidence_backed | runner_and_contract | app reachable | GET `/v1/system/readiness` | 200 | public route unexpectedly protected | API | system route contract | CI/local/shared_dev |
| CP-05 | operational_plane | metrics route emits Prometheus text and Ajenda metrics | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET metrics route | 200 + metrics exposition | blocked or malformed metrics route | API | observability metrics contract | CI/local/shared_dev |

### Auth + tenant envelope

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AT-01 | auth_tenant_envelope | missing tenant rejected on tenant-scoped route | P0 | SAFE_READ_ONLY | evidence_backed | contract_test | protected route available | omit `X-Tenant-Id` | 400 | request allowed to mutate | API | tenant middleware | CI/local/shared_dev |
| AT-02 | auth_tenant_envelope | invalid tenant UUID rejected | P0 | SAFE_READ_ONLY | evidence_backed | contract_test | protected route available | send malformed tenant ID | 400 | malformed tenant passes envelope | API | tenant middleware | CI/local/shared_dev |
| AT-03 | auth_tenant_envelope | missing auth rejected | P0 | SAFE_READ_ONLY | evidence_backed | contract_test | protected route available | omit auth on protected route | 401 | protected route accessible without auth | API | auth middleware | CI/local/shared_dev |
| AT-04 | auth_tenant_envelope | cross-tenant principal rejected | P0 | SAFE_READ_ONLY | evidence_backed | contract_test | tenant A principal, tenant B envelope | invoke protected route | 403 | cross-tenant access allowed | API | auth middleware cross-tenant check | CI/local/shared_dev |
| AT-05 | auth_tenant_envelope | public health/readiness/recovery remain publicly accessible | P1 | SAFE_READ_ONLY | partial | runner_and_contract | app reachable | invoke public routes without envelope | expected public access preserved | public infra/control routes inadvertently protected | API | tenant/auth public allowlists | CI/local/shared_dev |

### Execution plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EX-01 | execution_plane | single-task queue admission produces queued state and audit | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | admissible task exists | queue task | queued + audit | response success without authoritative queue state | API, DB, audit, Redis | execution coordinator, queue route | local/isolated/shared_dev with care |
| EX-02 | execution_plane | queue admission blocked for missing task or wrong tenant | P1 | SAFE_READ_ONLY | partial | integration_test | missing or foreign task | invoke queue admission | rejection | wrong-tenant task admitted | API, DB | task route + service | CI/local/shared_dev |
| EX-03 | execution_plane | mixed mission queue outcomes reflected in DB, not only API | P2 | TENANT_SCOPED_MUTATION | documented | docs_only | mixed admissible/pending-review tasks | queue mission/unit of work | DB reflects split outcomes | response-only truth with mismatched DB | API, DB | mission/execution coordinator | local/isolated |
| EX-04 | execution_plane | claim creates lease and records lease linkage | P1 | TENANT_SCOPED_MUTATION | implemented | integration_test | queued task and worker context | claim work | lease exists; task metadata links lease | claim without authoritative lease | DB | worker runtime service | local/isolated |
| EX-05 | execution_plane | start execution transitions claimed to running | P1 | TENANT_SCOPED_MUTATION | implemented | integration_test | claimed task exists | start execution | running state | claimed work runs without transition | DB | worker runtime service | local/isolated |
| EX-06 | execution_plane | complete transitions running to completed and drains processing | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | running task exists | complete work | completed + no processing leftovers | completed task still treated as in-flight | DB, Redis, audit, logs | worker runtime service | local/isolated |
| EX-07 | integrity_plane | duplicate active lease claim rejected | P0 | TENANT_SCOPED_MUTATION | implemented | integration_test | active lease exists | attempt second claim | duplicate claim rejected | two active authoritative claimants | DB | `_assert_no_active_lease` in worker runtime service | local/isolated |

### Failure + retry plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FR-01 | failure_plane | forced failure transitions to failed + dead-letter path as appropriate | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | deterministic fail task | fail execution | failed or valid dead-letter terminal outcome | silent error path | DB, Redis, audit, logs | worker runtime service / dispatcher | local/isolated |
| FR-02 | recovery_plane | stale claimed lease recovers claimed to queued | P1 | GLOBAL_MUTATION | evidence_backed | runner_and_integration | expired claimed lease | run recovery | re-queued claimed task | stale claimed task stranded | API, DB, audit | runtime maintainer | isolated_env_only |
| FR-03 | recovery_plane | stale running lease recovers with retry increment | P1 | GLOBAL_MUTATION | evidence_backed | runner_and_integration | expired running lease with retries remaining | run recovery | queued with incremented retry count | recovery without retry accounting | API, DB, audit | runtime maintainer | isolated_env_only |
| FR-04 | recovery_plane | retry exhaustion dead-letters stale running work | P1 | GLOBAL_MUTATION | evidence_backed | integration_test | expired running lease at retry ceiling | run recovery | dead-lettered state | infinite recovery loop | DB, audit | runtime maintainer | isolated_env_only |
| FR-05 | recovery_plane | recovery is idempotent for already-resolved expired work | P0 | GLOBAL_MUTATION | partial | integration_test | recovered or expired/resolved work present | run recovery again | no double increment / no double enqueue | repeated mutation of resolved work | DB, Redis, audit | runtime maintainer | isolated_env_only |

### Dead-letter plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DL-01 | dead_letter_plane | dead-letter inspection is tenant-scoped | P1 | SAFE_READ_ONLY | documented | docs_only | dead-lettered work exists across tenants | inspect dead-letter data | tenant-scoped visibility only | cross-tenant dead-letter exposure | API, DB | operations/webhook visibility surfaces as applicable | CI/local/shared_dev |
| DL-02 | dead_letter_plane | dead-letter retry legality enforced | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_and_integration | illegal retry target | invoke retry | 400 and unchanged state | illegal mutation or enqueue | API, DB | operations service + contract/integration tests | local/isolated |

### Integrity plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IN-01 | integrity_plane | no duplicate active lease for same task | P0 | TENANT_SCOPED_MUTATION | implemented | integration_test | existing active lease | attempt second active ownership | duplicate ownership prevented | two active authoritative leases | DB | worker runtime service | local/isolated |
| IN-02 | integrity_plane | completion leaves no queue-processing leftovers | P0 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | completed task exists | inspect post-completion state | no processing leftovers | completed task remains in processing | DB, Redis | worker runtime service + runner RG-06 | local/isolated |
| IN-03 | recovery_plane | recovery does not mutate healthy leases/tasks | P0 | GLOBAL_MUTATION | evidence_backed | runner_and_integration | healthy work present | run recovery | only stale work changes | healthy task drift | API, DB, audit | runtime maintainer + runner RG-11 | isolated_env_only |

### Observability plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OB-01 | observability_plane | worker happy path emits completion evidence | P2 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | completed task exists | inspect completion artifacts | audit and log evidence present | success path with no inspectable evidence | audit, logs | worker runtime + runner RG-06 | local/isolated |

### Compliance plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CO-01 | compliance_plane | policy denial results in pending_review with no enqueue | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | policy-denied task exists | attempt queue admission | pending_review + governance/audit evidence + no enqueue | denied task enters authoritative queue | API, DB, Redis, audit, governance | execution coordinator + policy path | local/isolated |

---

## Current runner-supported scenarios

The runner currently supports:

- RG-01
- RG-02
- RG-03
- RG-04
- RG-06
- RG-07
- RG-08
- RG-09
- RG-10
- RG-11
- RG-12

The current runner also emits:

- per-scenario dynamic result metadata
- a run-level `scenario_results.tsv` ledger
- a run-level `summary.json` manifest

This means:

- most release-gating runtime paths are executable through the runner
- RG-05 remains gate-critical but is primarily backed through contract-style validation surfaces rather than direct runner support today
- current runner executions now have one machine-readable whole-run summary surface in addition to scenario directories

---

## Current matrix interpretation

### What is strongest today

The strongest current matrix surfaces are:

- release-gating rows tied to contract/integration/runner evidence
- queue admission
- completion/failure evidence
- claimed/running recovery paths
- recovery safety
- pending-review denial path
- core tenant/auth boundary rejections

### What remains less mature

The less mature current matrix areas are:

- broader resilience-plane coverage
- deeper mixed-tenant concurrency proof
- stronger negative-space scenarios beyond core lease/recovery protections
- broader dead-letter inspection/operational visibility proof
- richer operational semantics around stale evidence and environment eligibility

These rows should remain visible rather than omitted.

---

## Forbidden-outcome principle

Enterprise validation is not only about proving success.
It is also about proving the absence of dangerous outcomes.

Every critical row should be interpreted against its forbidden result.

Examples of forbidden outcomes that matter across the matrix:

- public probes blocked
- protected status routes exposed without envelope
- cross-tenant access allowed
- duplicate active lease
- duplicate completion
- queue admission without authoritative queued state
- stale claimed/running work stranded
- double requeue on recovery
- healthy work mutated by recovery
- policy-denied task enqueued anyway
- completed task left in processing
- runtime success without audit or inspectable evidence where such evidence is expected

---

## How this matrix should be used

Use this matrix to guide:

- release-gating judgment
- runtime hardening priorities
- validation-run design
- documentation alignment
- operational confidence review

Do not treat it as a prettier test index.
Treat it as the runtime-proof contract for the governed execution system.

---

## Immediate hardening priorities

1. keep the matrix internally normalized
2. preserve the separation between static matrix truth and dynamic run truth
3. tighten runner/doc/test alignment
4. expand weaker resilience/isolation/integrity rows deliberately
5. maintain release gates as a compact, strict subset
