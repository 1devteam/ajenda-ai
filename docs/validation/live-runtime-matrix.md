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

Mission runtime task materialization validation currently proves explicit creation of planned `ExecutionTask` rows from a ready admitted mission graph only. Runtime dispatch readiness validation proves a read-only readiness view over current materialized, queue-admitted tasks. Worker execution start admission validation proves only a tenant-scoped controlled claimed-to-running mutation for current claim-admitted tasks with valid WorkerLease ownership; it must not be read as proof of handler execution, adapter execution, graph orchestration, scheduler behavior, task completion, or a full worker loop. Those remain separate runtime-validation concerns.

---

## Subsystem-lane proof alignment

The fourteen subsystem lanes are defined in `docs/product/mission-runtime-architecture-map.md` and remain governed by `docs/contracts/authority-ledger.v1.yaml`. Matrix rows should identify which lane or lane boundary they prove whenever a scenario changes runtime, queue, lease, tool/action, evidence, validation, tenant/auth, or declarative-governance behavior.

Release proof must not collapse lane boundaries. For example, mission intake proof does not prove queue admission; task graph proof does not prove materialization; materialization proof does not prove queue enqueue; queue admission proof does not prove lease ownership; lease/start proof does not prove dispatcher execution; and dispatcher/tool proof does not prove unrelated declarative API behavior. Where a lane is partial, future-facing, read-model only, or compatibility-only, the matrix must say so instead of promoting the scenario as complete runtime proof.

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
- `evidence_basis`

Current runner-generated dynamic artifact surfaces include:

- per-scenario files:
  - `run_outcome.txt`
  - `evidence_status.txt`
  - `notes.txt`
  - `validation_env.txt`
  - `evidence_basis.txt`
- run-level files:
  - `scenario_results.tsv`
  - `summary.json`

This keeps dynamic run truth inspectable at both the scenario level and the whole-run level. The run-level `summary.json` also reports `evidence_basis_counts` for `runner_backed`, `integration_backed`, and `unsupported` classifications.

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

### `evidence_basis`

Allowed values for a specific execution artifact:

- `runner_backed` — the runner executed the scenario proof directly
- `integration_backed` — the row is currently proven by integration tests, not by runner execution
- `unsupported` — the row is not currently supported by runnable validation tooling

### Artifact provenance boundary

`evidence_basis` is dynamic artifact provenance, not static matrix maturity. It answers what produced this run's scenario artifact. `validation_backing` is static matrix metadata and answers what repository surfaces are expected to prove the row in general.

Important review rules:

- A `not_executed` runner artifact with `integration_backed` provenance is a pointer to integration-test proof, not fresh runner evidence.
- A `runner_backed` artifact may be treated as direct live-runner proof only when the run outcome and evidence status are also trustworthy for the scenario.
- `unsupported` provenance must not satisfy release-gating evidence requirements.

---

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
- `not_executed`
- `evidence_incomplete`

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

Scenario exists in the matrix, but the runner did not execute it and the row must not be treated as runner-backed evidence; intentional integration-backed `not_executed` rows are recorded without failing the whole run by themselves.

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
| RG-08 | recovery_plane | stale claimed lease recovery re-queues safely | P1 | GLOBAL_MUTATION | authoritative_gate | integration_test | expired claimed lease exists with an authoritative queue payload | POST `/v1/operations/recovery` | claimed task re-queued, lease expired, and queue reconciled to exactly one pending payload | no-op on expired claimed work; duplicate pending payloads; synthetic replacement work after payload loss; unsafe mutation patterns | API, DB, Redis, audit | `backend/services/runtime_maintainer.py`, `backend/queue/base.py`, `backend/queue/adapters/redis_adapter.py`, `tests/integration/runtime/test_claim_start_failure_recovery_real.py`, `tests/integration/runtime/test_lease_recovery_real.py`, recovery integration tests; runner marks RG-08 not executed until seeded proof exists | isolated_env_only |
| RG-09 | recovery_plane | stale running lease recovery and retry/dead-letter path | P1 | GLOBAL_MUTATION | authoritative_gate | integration_test | expired active lease exists with processing or pending queue payload evidence | POST `/v1/operations/recovery` | running work atomically reconciles Redis processing/pending state to one pending payload and recovers to queued with retry accounting, or dead-letters at retry ceiling | stuck running work; illegal retry behavior; duplicate processing/pending residue; silent payload loss | API, DB, audit, Redis | `backend/services/runtime_maintainer.py`, `backend/queue/base.py`, `backend/queue/adapters/redis_adapter.py`, `tests/integration/runtime/test_runtime_recovery_queue_corruption_real.py`, `tests/integration/runtime/test_runtime_reconciliation_enforcement_real.py`, recovery integration tests; runner marks RG-09 not executed until seeded proof exists | isolated_env_only |
| RG-10 | dead_letter_plane | illegal dead-letter retry is rejected safely | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | contract_and_integration | task not in legal retry state | POST dead-letter retry route | illegal retry rejected, no mutation | illegal requeue or state change | API, DB | dead-letter operation contract + integration tests | local/isolated/shared_dev with care |
| RG-11 | recovery_plane | recovery mutates only stale work | P0 | GLOBAL_MUTATION | authoritative_gate | integration_test | recovery endpoint available; healthy work exists; terminal stale ownership and missing-payload stale work are represented | POST `/v1/operations/recovery` and inspect before/after | only recoverable expired/stale work changes; terminal stale ownership is expired without requeue; missing payload retry recovery with retries remaining fails closed and preserves DB task/lease state; retry-exhausted stale work follows the dead-letter path | healthy work mutation or drift; terminal stale work requeued; missing payload converted into synthetic queued work | API, DB, Redis, audit | `backend/services/runtime_maintainer.py`, `backend/queue/base.py`, `backend/queue/adapters/redis_adapter.py`, `tests/integration/runtime/test_runtime_reconciliation_enforcement_real.py`, recovery integration tests; runner marks RG-11 not executed until seeded proof exists | isolated_env_only |
| RG-12 | compliance_plane | policy denial routes task to pending review with no enqueue | P1 | TENANT_SCOPED_MUTATION | authoritative_gate | runner_and_integration | policy-denied task available | POST `/v1/tasks/{task_id}/queue` | 400 denial, pending_review/gov evidence, no enqueue | unsafe queue admission after policy denial | API, DB, Redis, audit, governance | execution coordinator + policy path + runner RG-12 | local/isolated/shared_dev with care |

---

## Broader runtime scenarios

Broader matrix rows expand operational truth beyond release gates. They are important even when they are not promotion-blocking.

### Recovery reconciliation evidence update

PR #110 and PR #111 strengthen the static recovery contract with integration-backed reconciliation invariants:

- expired claimed/running recovery must use queue payload authority rather than synthesizing replacement work from DB state
- recoverable stale work must converge Redis processing/pending state to exactly one pending payload for the task
- duplicate pending or processing residue is forbidden after recovery reconciliation
- missing payload retry recovery with retries remaining fails closed and preserves DB task/lease state; retry-exhausted stale work follows the dead-letter path
- terminal stale ownership is cleaned up by expiring the stale lease without requeueing terminal work

These are static evidence-alignment statements. Specific run outcomes and artifact paths still belong in validation-run output, not this matrix.

Current broader scenario count: **54**

### Control plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CP-01 | control_plane | root liveness public | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET `/health` | 200 | public liveness blocked | API | health route contract | CI/local/shared_dev |
| CP-02 | control_plane | root readiness validates runtime readiness path | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET `/readiness` | 200 when readiness is healthy | readiness exposed as meaningless success | API | health/readiness contract | CI/local/shared_dev |
| CP-03 | control_plane | system health route public | P2 | SAFE_READ_ONLY | evidence_backed | runner_and_contract | app reachable | GET `/v1/system/health` | 200 | public route unexpectedly protected | API | system route contract | CI/local/shared_dev |
| CP-04 | control_plane | system readiness route public | P2 | SAFE_READ_ONLY | evidence_backed | runner_and_contract | app reachable | GET `/v1/system/readiness` | 200 | public route unexpectedly protected | API | system route contract | CI/local/shared_dev |
| CP-05 | operational_plane | metrics route emits Prometheus text and Ajenda metrics | P2 | SAFE_READ_ONLY | evidence_backed | contract_test | app reachable | GET metrics route | 200 + metrics exposition | blocked or malformed metrics route | API | observability metrics contract | CI/local/shared_dev |
| CP-06 | control_plane | readiness dependency truth reports DB and queue state consistently | P1 | SAFE_READ_ONLY | evidence_backed | contract_and_unit | app reachable with controllable DB and queue dependency ping outcomes | GET `/readiness` and GET `/v1/system/readiness` with healthy and degraded dependency permutations | payload includes `dependencies.database.status` and `dependencies.queue.status`, status is `ready` only when both are ready/skipped, and degraded reasons map to `DATABASE_UNAVAILABLE`, `QUEUE_UNAVAILABLE`, or `DEPENDENCY_UNAVAILABLE` | readiness returns 200 with unavailable dependencies, omits dependency state, or exposes contradictory reason/status mapping | API | `backend/services/readiness_evaluator_service.py`, `tests/unit/services/test_readiness_evaluator_service.py`, `tests/contract/api/test_health_route.py` | CI/local/shared_dev |
| CP-07 | control_plane | readiness dependency failures are sanitized | P1 | SAFE_READ_ONLY | evidence_backed | contract_and_unit | app reachable; dependency ping can raise exception text containing sensitive connection details | GET `/readiness` and GET `/v1/system/readiness` when dependency ping raises | readiness fails closed with 503 and canonical reason while excluding raw exception details from response payload | readiness leaks raw dependency exception details or credentials in response body | API | `backend/services/readiness_evaluator_service.py`, `tests/unit/services/test_readiness_evaluator_service.py`, `tests/contract/api/test_health_route.py`, `tests/contract/api/test_system_status_routes.py` | CI/local/shared_dev |

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
| EX-24 | resilience_plane | mixed-tenant selective stale-lease recovery dead-letters only the expired exhausted tenant and preserves the healthy claim path | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, one tenant remains healthy and claimed, and the other tenant has both an expired lease and retry exhaustion | run bounded recovery with one healthy claimed lease still live and one stale retry-exhausted lease expired, then inspect per-tenant processing, lease-key, pending, and terminal DB state surfaces | only the expired exhausted tenant dead-letters once, the healthy tenant keeps claimed authority and processing residue intact, no pending requeue appears for the exhausted tenant, and no cross-tenant selective-recovery bleed occurs | selective recovery dead-letters or clears the healthy claim path, requeues the exhausted tenant incorrectly, or mutates the healthy tenant’s lease/process markers while handling the expired exhausted tenant | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_selective_recovery_real.py` | local/isolated |
| EX-25 | resilience_plane | mixed-tenant selective recovery preserves a healthy running tenant while dead-lettering only the expired exhausted peer | P1 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | two tenants each have their own queued task, concurrent claims have resolved one authoritative lease per tenant, one tenant has already started healthy running work, and the other tenant has both an expired lease and retry exhaustion | advance one tenant into running, expire the other tenant at retry ceiling, run bounded recovery, then inspect per-tenant processing, lease-key, pending, and terminal DB state surfaces | the healthy running tenant remains active with its processing and lease surfaces intact, only the expired exhausted tenant dead-letters once, and no cross-tenant selective-recovery bleed occurs | selective recovery mutates, clears, or terminalizes the healthy running tenant while handling the expired exhausted peer, or fails to isolate dead-letter mutation to the stale exhausted tenant | DB, Redis | `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_mixed_tenant_selective_recovery_real.py` | local/isolated |
| EX-26 | execution_plane | mission runtime dispatch readiness is read-only and task-type strict | P1 | SAFE_READ_ONLY | evidence_backed | contract_test | tenant mission has current runtime task materialization and admitted or partially admitted queue metadata | GET `/v1/missions/{mission_id}/runtime-dispatch-readiness` | ready/partial/blocked classification over current materialized task IDs, queued task count, explicit dispatcher `task_type` checks, blockers, warnings, and negative runtime-authority flags | creates tasks, enqueues work, calls executor/coordinator/task dispatcher, dispatches workers, executes adapters, blesses queued tasks without `task_type`, or exposes cross-tenant mission data | API, DB | `backend/api/routes/mission.py`, `tests/unit/api/test_runtime_dispatch_readiness_contract.py` | CI/local/shared_dev |
| EX-27 | execution_plane | worker dispatch eligibility is a read-only proof over current dispatch-ready queue tasks | P1 | SAFE_READ_ONLY | evidence_backed | contract_test | tenant mission has current runtime task materialization, current queue admission, and ready or partial runtime dispatch readiness | GET `/v1/missions/{mission_id}/worker-dispatch-eligibility` | eligible/partial/blocked classification over current materialized task IDs requiring tenant/mission ownership, current queue-admission materialized and admitted lists, dispatch readiness membership, queued DB state, and explicit `task_type` metadata | claims leases, mutates task state, mutates mission metadata, calls executor/coordinator/worker runtime/task dispatcher, touches queue backend state, executes handlers/adapters, schedules graph orchestration, or proves actual worker dispatch | API, DB | `backend/api/routes/mission.py`, `tests/unit/api/test_worker_dispatch_eligibility_contract.py` | CI/local/shared_dev |
| EX-28 | execution_plane | worker claim preview defines future worker handoff envelopes without claiming | P1 | SAFE_READ_ONLY | evidence_backed | contract_test | tenant mission has worker dispatch eligibility results with zero or more eligible tasks | GET `/v1/missions/{mission_id}/worker-claim-preview` | preview envelopes only for eligible tasks with queued-to-claimed expectations, lease scope, runtime contract requirements, source references, metadata summaries, blocked task reporting, and read-only/preview-only authority flags | creates WorkerLease rows, claims queue messages, starts execution, mutates task/mission state, calls worker claim/start/complete/fail paths, dispatches handlers/adapters, enqueues work, proves scheduler behavior, or proves actual worker lease claim/execution | API, DB | `backend/api/routes/mission.py`, `tests/unit/api/test_worker_dispatch_eligibility_contract.py` | CI/local/shared_dev |
| EX-29 | execution_plane | worker claim admission performs a tenant-scoped controlled claim mutation after preview | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_test | tenant mission has current worker claim preview eligibility for queued materialized queue-admitted dispatch-ready tasks | POST `/v1/missions/{mission_id}/worker-claim-admission`; GET `/v1/missions/{mission_id}/worker-claim-admission` | only current preview-eligible queued tasks with explicit `task_type` are transitioned to claimed through the canonical task state path, WorkerLease ownership is established without duplicate current-admission leases, claim receipts and authority metadata are persisted, blocked/partial cases are controlled, and GET readback is read-only | starts execution, dispatches workers, calls handlers/adapters/task dispatcher, enqueues work, calls queue admission or mission executor paths, completes/fails tasks, mutates graph/materialization/queue contracts beyond claim-admission metadata, proves scheduler behavior, proves adapter execution, proves graph orchestration, or proves full worker-loop completion | API, DB | `backend/api/routes/mission.py`, `tests/unit/api/test_worker_claim_admission_contract.py` | CI/local/shared_dev |
| EX-30 | execution_plane | worker execution start admission performs a tenant-scoped controlled start mutation after claim admission | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_test | tenant mission has admitted or partially admitted worker claim metadata with durable claimed task IDs, claim receipts, claimed DB task state, explicit `task_type`, and valid current WorkerLease ownership | POST `/v1/missions/{mission_id}/worker-start-admission`; GET `/v1/missions/{mission_id}/worker-start-admission` | only current claim-admitted claimed tasks with valid same-tenant/same-task WorkerLease holder and claimed/active lease status transition to running through the canonical state path, lease heartbeat/status follows runtime semantics, start receipts and authority metadata are persisted, retries are idempotent, blocked/partial cases are controlled, and GET readback is read-only | dispatches workers, executes handlers/adapters/task dispatcher, enqueues work, calls queue admission/coordinator/mission executor paths, creates WorkerLease rows, claims tasks, completes/fails tasks, mutates graph/materialization/queue/dispatch/claim contracts beyond start-admission metadata, proves scheduler behavior, proves adapter execution, proves graph orchestration, proves task completion, or proves full worker-loop behavior | API, DB | `backend/api/routes/mission.py`, `tests/unit/api/test_worker_start_admission_contract.py` | CI/local/shared_dev |
| EX-31 | execution_plane | worker run admission performs governed dispatcher execution for start-admitted running tasks | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_test | tenant mission has admitted or partially admitted worker start metadata with durable started task IDs, start receipts, running DB task state, explicit `task_type`, valid active WorkerLease ownership, and existing queue payload authority | POST `/v1/missions/{mission_id}/worker-run-admission`; GET `/v1/missions/{mission_id}/worker-run-admission` | only current start-admitted running tasks with valid same-tenant/same-task active WorkerLease ownership are admitted to the existing dispatcher/handler path after tenant/RLS-aware dispatcher sessions are established and the existing queue payload is claimed or confirmed processing for the same owner; queue-claim receipts, run receipts, terminal completion/failure metadata, idempotent readback, blocked/partial cases, and read-only GET authority are proven | scheduler behavior, full graph orchestration, automatic multi-task workflow execution, memory promotion, outcome review automation, enqueueing new work, running arbitrary unadmitted tasks, RLS bypass, synthetic queue payload recovery, queue backend rewrite, default_handler removal, or adapter execution beyond what the registered handler path already performs | API, DB, queue | `backend/api/routes/mission.py`, `backend/queue/base.py`, `backend/queue/local_adapter.py`, `backend/queue/adapters/redis_adapter.py`, `tests/unit/api/test_worker_run_admission_contract.py` | CI/local/shared_dev |

### Failure + retry plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FR-01 | failure_plane | forced failure transitions to failed + dead-letter path as appropriate | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | deterministic fail task | fail execution | failed or valid dead-letter terminal outcome | silent error path | DB, Redis, audit, logs | worker runtime service / dispatcher | local/isolated |
| FR-02 | recovery_plane | stale claimed lease recovers claimed to queued | P1 | GLOBAL_MUTATION | evidence_backed | integration_test | expired claimed lease with queue payload authority | run recovery | re-queued claimed task with reconciled single pending payload and expired lease | stale claimed task stranded; duplicate requeue; silent payload loss | API, DB, Redis, audit | runtime maintainer, queue adapter reconciliation, `tests/integration/runtime/test_claim_start_failure_recovery_real.py`, `tests/integration/runtime/test_lease_recovery_real.py` | isolated_env_only |
| FR-03 | recovery_plane | stale running lease recovers with retry increment | P1 | GLOBAL_MUTATION | evidence_backed | integration_test | expired running lease with retries remaining and processing or pending payload evidence | run recovery | queued with incremented retry count and exactly one reconciled pending payload | recovery without retry accounting; duplicate processing/pending residue; duplicate requeue; silent payload loss | API, DB, Redis, audit | runtime maintainer, Redis atomic recovery script, `tests/integration/runtime/test_runtime_recovery_queue_corruption_real.py`, `tests/integration/runtime/test_runtime_reconciliation_enforcement_real.py` | isolated_env_only |
| FR-04 | recovery_plane | retry exhaustion dead-letters stale running work | P1 | GLOBAL_MUTATION | evidence_backed | integration_test | expired running lease at retry ceiling | run recovery | dead-lettered state | infinite recovery loop | DB, audit | runtime maintainer | isolated_env_only |
| FR-05 | recovery_plane | recovery is idempotent for already-resolved expired work | P0 | GLOBAL_MUTATION | evidence_backed | integration_test | recovered, expired/resolved, terminal stale ownership, or missing-payload stale work present | run recovery again | no double increment / no double enqueue; terminal stale ownership expires without requeue; missing-payload retry recovery with retries remaining fails closed without DB state mutation; retry-exhausted stale work follows the dead-letter path | repeated mutation of resolved work; terminal stale ownership requeued; synthetic queued work created after payload loss | DB, Redis, audit | runtime maintainer, queue adapter reconciliation, `tests/integration/runtime/test_lease_recovery_real.py`, `tests/integration/runtime/test_runtime_reconciliation_enforcement_real.py` | isolated_env_only |
| FR-06 | recovery_plane | protected recovery route returns the full bounded summary including dead-letter outcomes | P2 | GLOBAL_MUTATION | evidence_backed | contract_test | recovery route is invoked through the API boundary with a valid tenant/auth envelope and operator/admin runtime authorization; unauthorized callers are rejected without service invocation | POST `/v1/operations/recovery` and inspect the response payload | response exposes `expired_lease_count`, `requeued_task_count`, and `dead_lettered_count` exactly as returned by the service boundary for authorized callers | public recovery access; recovery route drops dead-letter outcomes or rewrites the bounded summary emitted by the service | API | `backend/api/routes/operations.py`, `tests/contract/operations/test_recovery_contract.py`, `tests/contract/operations/test_recovery_public_contract.py` | CI/local/shared_dev |

### Dead-letter plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DL-01 | dead_letter_plane | dead-letter inspection is tenant-scoped | P1 | SAFE_READ_ONLY | evidence_backed | contract_and_integration | dead-lettered work exists across tenants | inspect dead-letter data | tenant-scoped visibility only | cross-tenant dead-letter exposure | API, DB | `backend/api/routes/operations.py`, `backend/services/operations_service.py`, `tests/contract/operations/test_dead_letter_inspection_contract.py`, `tests/integration/operations/test_dead_letter_inspection_real.py` | CI/local/shared_dev |
| DL-02 | dead_letter_plane | dead-letter retry legality enforced | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_and_integration | illegal retry target | invoke retry | 400 and unchanged state | illegal mutation or enqueue | API, DB | operations service + contract/integration tests | local/isolated |
| DL-03 | dead_letter_plane | dead-letter inspection excludes non-dead-letter rows even when the tenant has mixed terminal and non-terminal work | P2 | SAFE_READ_ONLY | evidence_backed | integration_test | a tenant has dead-letter, completed, queued, and failed tasks at the same time | inspect dead-letter data for that tenant | only dead-lettered rows are returned for that tenant | inspection leaks non-dead-letter rows into dead-letter operational visibility | DB | `backend/services/operations_service.py`, `tests/integration/operations/test_dead_letter_inspection_real.py` | CI/local/shared_dev |
| DL-04 | dead_letter_plane | dead-letter inspection returns an empty result for a tenant with no dead-lettered work | P2 | SAFE_READ_ONLY | evidence_backed | contract_and_integration | a tenant has terminal or in-flight work but no dead-letter rows | inspect dead-letter data for that tenant | empty result set is returned | inspection fabricates dead-letter visibility or leaks non-dead-letter rows when none exist | API, DB | `backend/api/routes/operations.py`, `backend/services/operations_service.py`, `tests/contract/operations/test_dead_letter_inspection_contract.py`, `tests/integration/operations/test_dead_letter_inspection_real.py` | CI/local/shared_dev |
| DL-05 | dead_letter_plane | dead-letter inspection stays empty when only another tenant has dead-lettered work | P2 | SAFE_READ_ONLY | evidence_backed | integration_test | target tenant has no dead-letter rows while a different tenant does have dead-lettered work | inspect dead-letter data for the clean tenant | empty result set is returned for the clean tenant | inspection leaks another tenant’s dead-letter rows into the clean tenant’s visibility | DB | `backend/services/operations_service.py`, `tests/integration/operations/test_dead_letter_inspection_real.py` | CI/local/shared_dev |
| DL-06 | dead_letter_plane | dead-letter retry route preserves request tenant and task context into the service boundary | P2 | TENANT_SCOPED_MUTATION | evidence_backed | contract_test | retry route is invoked with a tenant-scoped request and a concrete task id | invoke dead-letter retry route and observe the service call boundary | service receives the exact request tenant id and task id supplied by the route boundary | route drops, rewrites, or mismatches tenant/task context before service invocation | API | `backend/api/routes/operations.py`, `tests/contract/operations/test_dead_letter_retry_contract.py` | CI/local/shared_dev |

### Integrity plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IN-01 | integrity_plane | no duplicate active lease for same task | P0 | TENANT_SCOPED_MUTATION | evidence_backed | integration_test | existing active lease | attempt second active ownership | duplicate ownership prevented and queue claim compensated cleanly | two active authoritative leases or queue claim stranded in processing | DB, Redis | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py` | local/isolated |
| IN-02 | integrity_plane | completion leaves no queue-processing leftovers | P0 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | completed task exists | inspect post-completion state | no processing leftovers and duplicate completion rejected without extra audit | completed task remains in processing or duplicate completion mutates runtime state | DB, Redis, audit | `backend/services/worker_runtime_service.py`, `tests/integration/runtime/test_release_gating_runtime_real.py`, runner RG-06 | local/isolated |
| IN-03 | recovery_plane | recovery does not mutate healthy leases/tasks | P0 | GLOBAL_MUTATION | evidence_backed | integration_test | healthy work present | run recovery | only stale work changes | healthy task drift | API, DB, audit | runtime maintainer integration tests; runner marks RG-11 not executed until seeded proof exists | isolated_env_only |

### Observability plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OB-01 | observability_plane | worker happy path emits completion evidence | P2 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | completed task exists | inspect completion artifacts | audit and log evidence present | success path with no inspectable evidence | audit, logs | worker runtime + runner RG-06 | local/isolated |

### Compliance plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CO-01 | compliance_plane | policy denial results in pending_review with no enqueue | P1 | TENANT_SCOPED_MUTATION | evidence_backed | runner_and_integration | policy-denied task exists | attempt queue admission | pending_review + governance/audit evidence + no enqueue | denied task enters authoritative queue | API, DB, Redis, audit, governance | execution coordinator + policy path | local/isolated |

---

### Capability action runtime plane

| ID | Domain | Scenario | Priority | Safety Class | Matrix Status | Validation Backing | Preconditions | Action | Expected Result | Forbidden Result | Evidence Sources | Implementation Mapping | Execution Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AR-01 | action_runtime_plane | queued `tool.invoke` task executes through existing dispatcher and persists evidence-shaped output | P1 | TENANT_SCOPED_MUTATION | evidence_backed | contract_and_integration | planned task is queued, claimed, and started through existing runtime authority | run `TaskDispatcher` for `task_type=tool.invoke` | `ToolRuntimeAuthority` gates invocation/authority, registered action executes through `ActionRegistry`, task completes, lease releases, queue processing cleans up, lineage stores structured validated `ActionResult`/`EvidenceItem` output, and completed action evidence is bridged into tenant-owned EvidenceRecord rows | direct action execution outside queue/lease/dispatcher path, missing lineage output, missing durable evidence bridge output, unvalidated handler output, stuck lease or processing residue | DB, Redis, LineageRecord, EvidenceRecord, unit tests | `backend/workers/task_dispatcher.py`, `backend/workers/handlers/tool_invoke.py`, `backend/services/tools/runtime_authority.py`, `backend/services/tools/action_registry.py`, `backend/services/tools/evidence_bridge.py`, `tests/unit/tools/test_action_registry.py`, `tests/unit/tools/test_evidence_bridge.py`, `tests/unit/workers/test_tool_invoke_handler.py`, `tests/integration/runtime/test_worker_executes_tool_invoke_task_real.py` | local/isolated/shared_dev with care |
| AR-02 | action_runtime_plane | side-effecting actions fail closed without explicit versioned concrete authority | P0 | TENANT_SCOPED_SIDE_EFFECT_GATE | evidence_backed | contract_test | `tool.invoke` references `record.write`, `sales.log_activity`, `calendar.create_event`, `http.request` write method, or `webhook.dispatch` | invoke action without exact `execution_constraints.side_effect_authorization`, concrete capability/adapter action scope, or matching effective side-effect classification | invocation fails before provider execution and dispatcher failure path remains authoritative | side effect occurs merely because the action is registered, because broad `tool.invoke` is present, or because external read/write/send/publish classes collapse | unit tests | `backend/workers/handlers/tool_invoke.py`, `backend/services/tools/runtime_authority.py`, `backend/services/tools/capability_validation.py`, `backend/services/tools/schemas.py`, `tests/unit/tools/test_capability_action_validation.py`, `tests/unit/workers/test_tool_invoke_handler.py` | CI/local |
| AR-03 | action_runtime_plane | shared network egress rejects unsafe HTTP/webhook destinations before network call | P0 | EXTERNAL_ACCESS_GUARD | evidence_backed | contract_test | `http.request` or `webhook.dispatch` attempts outbound HTTPS | validate HTTPS/public URL, fail-closed DNS resolution, DNS pinning, Host/SNI preservation, fresh no-keepalive clients, per-request connection close, disabled redirects, and bounded response capture through `NetworkEgressAuthority` | localhost, `.local`, internal hostnames, private/link-local/loopback/multicast/reserved IP literals, private DNS resolutions, DNS failures, DNS rebinding, unsafe redirects, and unbounded responses are rejected or controlled | SSRF-style access to internal services, metadata endpoints, or a post-vetting rebound target | unit tests | `backend/services/network_egress.py`, `backend/services/tools/http_actions.py`, `backend/services/webhook_dispatch.py`, `tests/unit/tools/test_http_actions.py`, `tests/unit/webhooks/test_webhook_dispatch.py` | CI/local |

## Current runner-supported scenarios

The runner currently provides direct runner-backed proof for:

- RG-01
- RG-02
- RG-03
- RG-04
- RG-05
- RG-06
- RG-07
- RG-10
- RG-12

The runner accepts these recovery row IDs only to emit explicit `not_executed` artifacts with `integration_backed` evidence basis until seeded, row-specific proof exists:

- RG-08
- RG-09
- RG-11
- FR-02
- FR-03
- FR-05

These rows are integration-backed only and are not runner-backed.

The current runner also emits:

- per-scenario dynamic result metadata
- a run-level `scenario_results.tsv` ledger
- a run-level `summary.json` manifest

This means:

- recovery rows are not treated as runner-backed unless the runner has seeded, row-specific execution proof
- current runner executions have machine-readable whole-run summary and per-row evidence-basis surfaces in addition to scenario directories

---

## Product-layer runtime bridge note

Graph-to-runtime admission contracts are now present as a Mission-Based AI product-layer bridge. They validate and persist admission metadata only; they are not live graph execution proof, do not enqueue runtime work, and do not demonstrate parallel DAG scheduling or worker dispatch from graph nodes. The runtime admission readiness gate is also pre-execution validation only: it is a read-only eligibility check for future task materialization and does not create tasks, queue work, execute graph nodes, or dispatch workers. Runtime task materialization preview is likewise pre-materialization only: it shows which `ExecutionTask` rows and payload envelopes would be produced from a ready admitted graph, but it does not create tasks, queue work, execute adapters, call runtime coordinators/executors, or prove graph execution. Existing live-runtime proof claims remain limited to the queue-backed runtime paths explicitly covered by this matrix.

## Current matrix interpretation

### What is strongest today

The strongest current matrix surfaces are:

- release-gating rows tied to contract/integration/runner evidence
- queue admission
- completion/failure evidence
- claimed/running recovery paths
- recovery safety
- recovery route summary exposure including bounded dead-letter counts
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
- mixed-tenant selective dead-letter recovery preserving the healthy claim path while terminalizing only the expired exhausted tenant
- mixed-tenant selective recovery preserving a healthy running tenant while terminalizing only the expired exhausted peer
- tenant-scoped dead-letter inspection with contract and integration backing
- dead-letter inspection filtering out non-dead-letter rows under mixed tenant task states
- dead-letter inspection returning an empty result when a tenant has no dead-letter work
- dead-letter inspection staying empty even when another tenant does have dead-letter work
- dead-letter retry route preserving request tenant and task context into the service boundary

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
