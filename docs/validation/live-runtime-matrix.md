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
| RG-05 | auth_tenant_envelope | invalid or missing envelope is rejected without side effects | P0 | SAFE_READ_ONLY | authoritative_gate | runner_and_contract | tenant-scoped route available | invoke protected routes with missing/invalid tenant/auth | request rejected with no mutation | mutation or enqueue on invalid envelope | API | `backend/middleware/tenant_context.py`, `backend/middleware/auth_context.py`, tenant isolation contract tests + runner RG-05 | CI/local/shared_dev |
| RG-06 | execution_plane | queued task completes cleanly | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | valid queued task and worker path | exercise worker completion path | task reaches completed, lease released, audit/log evidence present | duplicate completion, stuck processing, missing release path | DB, Redis, audit, logs | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py`, runtime integration + runner RG-06 | local/isolated/shared_dev with care |
| RG-07 | failure_plane | forced failure reaches valid failure terminal path | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | deterministic fail task available | exercise failure path | task enters `failed` or valid dead-letter terminal state with evidence | silent failure, missing audit, invalid terminal path | DB, Redis, audit, logs | worker runtime + dispatcher + runner RG-07 | local/isolated/shared_dev with care |
| RG-08 | recovery_plane | stale claimed lease recovery re-queues safely | P1 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | expired claimed lease exists | POST `/v1/operations/recovery` | claimed task re-queued and lease expired | no-op on expired claimed work; unsafe mutation patterns | API, DB, audit | `backend/services/runtime_maintainer.py`, recovery integration + runner RG-08 | isolated_env_only |
| RG-09 | recovery_plane | stale running lease recovery and retry/dead-letter path | P1 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | expired active lease exists | POST `/v1/operations/recovery` | running work recovers to queued or dead-lettered according to retry state | stuck running work; illegal retry behavior | API, DB, audit, Redis | `backend/services/runtime_maintainer.py`, recovery integration + runner RG-09 | isolated_env_only |
| RG-10 | dead_letter_plane | illegal dead-letter retry is rejected safely | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | contract_and_integration | task not in legal retry state | POST dead-letter retry route | illegal retry rejected, no mutation | illegal requeue or state change | API, DB | dead-letter operation contract + integration tests | local/isolated/shared_dev with care |
| RG-11 | recovery_plane | recovery mutates only stale work | P0 | GLOBAL_MUTATION | authoritative_gate | runner_and_integration | recovery endpoint available; healthy work exists | POST `/v1/operations/recovery` and inspect before/after | only expired/stale work changes | healthy work mutation or drift | API, DB, audit | recovery service + runner RG-11 | isolated_env_only |
| RG-12 | compliance_plane | policy denial routes task to pending review with no enqueue | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | policy-denied task available | POST `/v1/tasks/{task_id}/queue` | 400 denial, pending_review/gov evidence, no enqueue | unsafe queue admission after policy denial | API, DB, Redis, audit, governance | execution coordinator + policy path + runner RG-12 | local/isolated/shared_dev with care |

---

## Broader runtime scenarios

Broader matrix rows expand operational truth beyond release gates. They are important even when they are not promotion-blocking.

Current broader scenario count: **45**

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
| AT-05 | auth_tenant_envelope | public health/readiness/recovery remain publicly accessible | P1 | partial | runner_and_contract | app reachable | invoke public routes without envelope | expected public access preserved | public infra/control routes inadvertently protected | API | tenant/auth public allowlists | CI/local/shared_dev |

### Execution plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EX-01 | execution_plane | single-task queue admission produces queued state and audit | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | admissible task exists | queue task | queued + audit | response success without authoritative queue state | API, DB, audit, Redis | execution coordinator, queue route | local/isolated/shared_dev with care |
| EX-02 | execution_plane | queue admission blocked for missing task or wrong tenant | P1 | SAFE_READ_ONLY | partial | integration_test | missing or foreign task | invoke queue admission | rejection | wrong-tenant task admitted | API, DB | task route + service | CI/local/shared_dev |
| EX-03 | execution_plane | mixed mission queue outcomes reflected in DB, not only API | P2 | TENANT_SCOPED_MUTATION | documented | docs_only | mixed admissible/pending-review tasks | queue mission/unit of work | DB reflects split outcomes | response-only truth with mismatched DB | API, DB | mission/execution coordinator | local/isolated |
| EX-04 | execution_plane | claim creates lease and records lease linkage | P1 | TENANT_SCOPED_MUTATION | implemented | integration_test | queued task and worker context | claim work | lease exists; task metadata links lease | claim without authoritative lease | DB | worker runtime service | local/isolated |
| EX-05 | execution_plane | start execution transitions claimed to running | P1 | TENANT_SCOPED_MUTATION | implemented | integration_test | claimed task exists | start execution | running state | claimed work runs without transition | DB | worker runtime service | local/isolated |
| EX-06 | execution_plane | complete transitions running to completed and drains processing | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | running task exists | complete work | completed + no processing leftovers | completed task still treated as in-flight | DB, Redis, audit, logs | worker runtime service + runner RG-06 | local/isolated |
| EX-07 | integrity_plane | duplicate active lease claim rejected | P0 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | active lease exists | attempt second claim | duplicate claim rejected and queue claim compensated without a new lease | two active authoritative claimants or queue claim stranded in processing | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-08 | resilience_plane | long-running dispatch maintains mid-flight heartbeat until completion | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | running task dispatched through a long-lived handler | execute long-running handler under dispatcher heartbeat loop | task stays running with advancing heartbeat, then completes cleanly | healthy long-running work loses lease liveness or recovers while still executing | DB, audit | `backend/workers/task_dispatcher.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-09 | resilience_plane | started work interrupted before completion recovers safely on lease expiry | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | task has started execution and worker disappears before complete/fail | let started work go stale, then run bounded stale-lease recovery | task re-queues with retry increment, lease expires, and no false terminal success/failure audit is written | interrupted running work strands forever or is mutated into false terminal success/failure | DB, Redis, audit | `backend/services/worker_runtime_service.py`, `backend/services/runtime_maintainer.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-10 | resilience_plane | queue interruption during enqueue rolls back authoritative state cleanly | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | task is queue-admissible but enqueue path fails before queue placement | attempt queue admission while queue adapter returns enqueue failure | task reverts to pre-queue state and no false queued audit is written | task remains authoritatively queued in DB without queue placement or emits false queued audit | DB, audit | `backend/services/execution_coordinator.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-11 | resilience_plane | transient enqueue interruption clears and subsequent retry queues cleanly | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | task is queue-admissible and first enqueue attempt fails transiently before queue availability returns | fail first enqueue attempt, then retry queue admission after queue availability is restored | first attempt rolls back cleanly; second attempt reaches authoritative queued state with a single truthful queued audit | repeated retry leaves task stranded in pre-queue state or emits duplicate/false queued audit | DB, Redis, audit | `backend/services/execution_coordinator.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-12 | resilience_plane | queued work survives service restart boundary and remains claimable exactly once | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | task has already reached authoritative queued state before service/session boundary is recreated | recreate service/session boundary, then claim queued work from fresh runtime context | queued task remains authoritative across restart boundary, produces a real lease on first claim, and is not claimable a second time | restart boundary loses queued work or allows duplicate post-restart claim | DB, Redis | `backend/services/execution_coordinator.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-13 | resilience_plane | claimed lease survives service restart boundary and continues to a single clean completion | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | task is already claimed with authoritative lease before service/session boundary is recreated | recreate service/session boundary, continue execution under same lease, then complete from fresh runtime context | claimed lease and task survive restart boundary, complete once, release lease, and reject any second completion attempt | restart boundary loses claimed authority or allows duplicate completion after restart | DB, Redis, audit | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-14 | resilience_plane | concurrent same-tenant claim timing yields exactly one claim and one authoritative lease | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | a single queued task exists while two fresh runtime contexts attempt claim at the same time | issue concurrent claim attempts against the same tenant/task window | exactly one claim succeeds, the other gets no task, and only one claimed lease exists | timing race creates duplicate claimed authority or duplicate lease rows for the same task | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-15 | resilience_plane | mixed-tenant concurrent claim pressure remains tenant-isolated | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task while fresh runtime contexts claim concurrently | issue concurrent claim attempts for separate tenants at the same time | each worker claims only its own tenant task and each tenant gets exactly one lease for its own task | cross-tenant claim bleed or lease/task mismatch across tenants under concurrent pressure | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| EX-16 | resilience_plane | same-tenant concurrent claim race leaves no duplicate processing residue after the losing side exits | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | a single queued task exists while two fresh runtime contexts attempt a same-tenant claim race | issue concurrent claim attempts, let one win, then inspect processing and lease surfaces after the losing side exits | exactly one processing entry remains, exactly one lease key remains, and exactly one claimed DB lease exists for the task | losing-side race residue leaves duplicate processing state, duplicate lease markers, or lease/task mismatch | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_concurrent_claim_cleanup_real.py` | local/isolated |
| EX-17 | resilience_plane | same-tenant claim-race winner later expires and recovery requeues once without recreating duplicate residue | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | a same-tenant claim race has already resolved to one authoritative claimed lease and that winning lease later goes stale | expire the winning lease after the race, run bounded recovery, then inspect queue and lease surfaces | the task requeues once with one retry increment, processing residue is cleared, lease key is cleared, and no duplicate residue is recreated | post-race recovery duplicates requeue state, leaves stale processing markers, or recreates extra lease residue | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_concurrent_claim_cleanup_real.py` | local/isolated |
| EX-18 | resilience_plane | previously raced work reaches retry exhaustion and dead-letters once without duplicate residue | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | a same-tenant claim race has already resolved to one authoritative claimed lease and the winning work has reached retry exhaustion before stale-lease recovery runs | expire the winning exhausted lease after the race, run bounded recovery, then inspect dead-letter, queue, and lease surfaces | the task dead-letters once, no requeue occurs, processing residue is cleared, lease key is cleared, and no duplicate dead-letter residue is created | post-race exhaustion causes duplicate dead-lettering, duplicate requeue, stale processing markers, or extra lease residue | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_concurrent_claim_dead_letter_real.py` | local/isolated |
| EX-19 | resilience_plane | same-tenant claim-race winner later completes cleanly without leaving duplicate terminal residue | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | a same-tenant claim race has already resolved to one authoritative claimed lease and the winning claimant later completes the work | continue the winning task from the claimed lease through running to completion, then inspect processing, lease, and DB terminal surfaces | the task completes once, processing is drained, the lease key is cleared, and the single authoritative lease is released with no duplicate terminal residue | post-race completion leaves stale processing state, stale lease markers, or allows duplicate terminal cleanup artifacts | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_concurrent_claim_cleanup_real.py` | local/isolated |
| EX-20 | resilience_plane | mixed-tenant post-race cleanup symmetry preserves isolated completion and recovery cleanup surfaces | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, and each tenant then advances through its own cleanup path | continue one mixed-tenant race pair through completion cleanup and another through stale-lease recovery cleanup, then inspect per-tenant processing, lease, and terminal/requeue surfaces | each tenant cleans up only its own processing and lease surfaces, terminal or recovery outcomes stay isolated, and no cross-tenant cleanup bleed or residue appears | cleanup for one tenant drains, releases, expires, or requeues artifacts belonging to the other tenant, or leaves cross-tenant residue after mixed post-race cleanup | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_concurrent_cleanup_real.py` | local/isolated |
| EX-21 | resilience_plane | mixed-tenant post-race dead-letter exhaustion stays isolated across cleanup surfaces | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, and both winning tasks reach retry exhaustion before stale-lease recovery runs | expire both mixed-tenant winning leases at retry ceiling, run bounded recovery, then inspect per-tenant dead-letter, processing, lease-key, and pending surfaces | each tenant dead-letters only its own task once, processing and lease-key residue clears per tenant, no pending requeue appears, and no cross-tenant dead-letter cleanup bleed occurs | dead-letter cleanup for one tenant mutates, clears, or recreates queue or lease residue for the other tenant, or creates duplicate terminal residue across tenants | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_concurrent_cleanup_real.py` | local/isolated |
| EX-22 | resilience_plane | mixed-tenant asymmetric post-race cleanup preserves isolated terminal outcomes and cleanup surfaces | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, and the two tenants then diverge into different cleanup outcomes | continue one mixed-tenant winning task through completion while the other reaches retry-exhausted stale-lease recovery, then inspect per-tenant processing, lease-key, pending, and terminal DB surfaces | each tenant retains only its own outcome and cleanup artifacts, the completion side releases cleanly, the exhausted side dead-letters cleanly, and no cross-tenant cleanup bleed or residue appears | one tenant’s cleanup path drains, releases, expires, dead-letters, or recreates residue for the other tenant, or asymmetric outcomes collapse into cross-tenant state bleed | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_concurrent_cleanup_real.py` | local/isolated |
| EX-23 | resilience_plane | mixed-tenant selective stale-lease recovery mutates only expired work and leaves healthy claimed work untouched | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, and only one of the two leases has actually expired | run bounded recovery with one healthy claimed lease still live and one stale claimed lease expired, then inspect per-tenant processing, lease-key, pending, and DB state surfaces | only the expired tenant path requeues and expires its lease, the healthy tenant path keeps its claimed authority and processing residue intact, and no cross-tenant selective-recovery bleed occurs | selective recovery mutates healthy claimed work, clears the healthy tenant’s lease/process markers, or fails to isolate stale-only mutation to the expired tenant | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_selective_recovery_real.py` | local/isolated |

### Failure + retry plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FR-01 | failure_plane | forced failure transitions to failed + dead-letter path as appropriate | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | deterministic fail task | fail execution | failed or valid dead-letter terminal outcome | silent error path | DB, Redis, audit, logs | worker runtime service / dispatcher | local/isolated |
| FR-02 | recovery_plane | stale claimed lease recovers claimed to queued | P1 | GLOBAL_MUTATION | evidence_backed | runner_and_integration | expired claimed lease | run recovery | re-queued claimed task | stale claimed task stranded | API, DB, audit | runtime maintainer | isolated_env_only |
| FR-03 | recovery_plane | stale running lease recovers with retry increment | P1 | GLOBAL_MUTATION | evidence_backed | runner_and_integration | expired running lease with retries remaining | run recovery | queued with incremented retry count | recovery without retry accounting | API, DB, audit | runtime maintainer | isolated_env_only |
| FR-04 | recovery_plane | retry exhaustion dead-letters stale running work | P1 | GLOBAL_MUTATION | evidence_backed | integration_test | expired running lease at retry ceiling | run recovery | dead-lettered state | infinite recovery loop | DB, audit | runtime maintainer | isolated_env_only |
| FR-05 | recovery_plane | recovery is idempotent for already-resolved expired work | P0 | GLOBAL_MUTATION | evidence_backed | integration_test | recovered or expired/resolved work present | run recovery again | no double increment / no double enqueue | repeated mutation of resolved work | DB, Redis, audit | runtime maintainer, `tests/integration/runtime/test_lease_recovery_real.py` | isolated_env_only |

### Dead-letter plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DL-01 | dead_letter_plane | dead-letter inspection is tenant-scoped | P1 | SAFE_READ_ONLY | evidence_backed | contract_and_integration | dead-lettered work exists across tenants | inspect dead-letter data | tenant-scoped visibility only | cross-tenant dead-letter exposure | API, DB | `backend/api/routes/operations.py`, `backend/services/operations_service.py`, `tests/contract/operations/test_dead_letter_inspection_contract.py`, `tests/integration/operations/test_dead_letter_inspection_real.py` | CI/local/shared_dev |
| DL-02 | dead_letter_plane | dead-letter retry legality enforced | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_and_integration | illegal retry target | invoke retry | 400 and unchanged state | illegal mutation or enqueue | API, DB | operations service + contract/integration tests | local/isolated |

### Integrity plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IN-01 | integrity_plane | no duplicate active lease for same task | P0 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | existing active lease | attempt second active ownership | duplicate ownership prevented and queue claim compensated cleanly | two active authoritative leases or queue claim stranded in processing | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| IN-02 | integrity_plane | completion leaves no queue-processing leftovers | P0 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | completed task exists | inspect post-completion state | no processing leftovers and duplicate completion rejected without extra audit | completed task remains in processing or duplicate completion mutates runtime state | DB, Redis, audit | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py`, runner RG-06 | local/isolated |
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
- RG-05
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

- the complete current release-gating set is executable through the runner
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
- repeated recovery idempotency for already-resolved work
- duplicate active lease rejection with clean queue compensation
- duplicate completion rejection without processing regression
- mid-flight heartbeat maintenance during long-running dispatch
- interrupted started-work recovery through bounded stale-lease recovery
- authoritative enqueue rollback on queue interruption
- transient queue reconnect recovery at the admission boundary
- queued-state persistence across service restart boundary with single post-restart claim
- claimed-lease continuity across service restart boundary with single clean completion
- concurrent same-tenant claim timing yielding one claim and one lease
- mixed-tenant concurrent claim isolation under live claim pressure
- same-tenant claim-race cleanup leaving one processing entry and one lease artifact set
- post-race recovery requeue leaving no duplicate residue recreation
- post-race dead-letter exhaustion leaving one bounded terminal outcome with no duplicate residue
- post-race completion leaving one clean terminal cleanup path with no duplicate residue
- mixed-tenant post-race cleanup symmetry preserving isolated completion and recovery cleanup surfaces
- mixed-tenant post-race dead-letter exhaustion preserving isolated terminal cleanup surfaces
- mixed-tenant asymmetric post-race cleanup preserving isolated divergent terminal outcomes
- mixed-tenant selective recovery preserving healthy claimed authority while mutating only expired work
- tenant-scoped dead-letter inspection with contract and integration backing

### What remains less mature

The less mature current matrix areas are:

- broader resilience-plane coverage
- deeper mixed-tenant concurrency proof beyond core claim isolation
- stronger negative-space scenarios beyond core lease/recovery protections
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
