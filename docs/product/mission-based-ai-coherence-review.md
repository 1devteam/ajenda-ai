# Mission-Based AI Coherence Review

## 1. Executive verdict

**Verdict: partially aligned.**

Current `main` aligns strongly with Mission-Based AI as a governed runtime foundation, but it is not yet a truly mission-based product layer.

The repository already proves the lower platform responsibilities that Mission-Based AI depends on: tenant-scoped admission, queue authority, leases, recovery, pending-review governance, audit events, lineage output for selected handlers, and live validation artifacts. That foundation is real and should be preserved.

The gap is the missing top layer. Today, missions mostly group planned execution tasks and provide a queue-all API. The code does not yet model mission intake, success criteria, mission planning, task graph generation, capability selection, outcome review, or memory promotion as first-class product concepts. The runtime can execute governed work, but the product does not yet convert a human outcome into a governed mission system.

## 2. Existing architecture fit

| Mission-Based AI layer | Current fit | Existing files/components | Coherence assessment |
|---|---|---|---|
| Mission/intake | Thin seed exists. | `backend/domain/mission.py`, `backend/repositories/mission_repository.py`, `backend/api/routes/mission.py` | A canonical `Mission` record exists with `objective`, tenant ownership, status, compliance category, jurisdiction, and metadata. The API currently queues existing planned tasks for a mission; it does not yet accept business-language outcomes or capture constraints/success criteria as first-class fields. |
| Planning | Mostly missing. | `backend/domain/mission.py`, `backend/domain/execution_task.py` | Planned tasks exist via `ExecutionTask.status == planned`, but no `MissionPlan`, decomposition service, planner contract, plan versioning, or operator-editable plan model exists. |
| Task graph | Mostly missing. | `backend/domain/execution_task.py`, `backend/domain/execution_branch.py`, `backend/repositories/execution_task_repository.py` | Tasks belong to a mission and may reference branches/fleets/agents, but there is no explicit graph edge/dependency model, ordering semantics, DAG validation, graph review UI/API, or task graph evidence. |
| Capability registry | Missing as product concept; handler registry exists as runtime mechanism. | `backend/workers/task_dispatcher.py` | `_HANDLER_REGISTRY` maps `task_type` strings to handler functions. This is useful as an execution extension point, but it lacks declared capability names, schemas, permissions, risk levels, approval rules, evidence contracts, tenant/plan enablement, or module metadata. |
| Worker execution | Strong foundation. | `backend/workers/task_dispatcher.py`, `backend/services/worker_runtime_service.py`, `backend/services/execution_coordinator.py`, queue adapter, worker tests | The dispatcher claims tasks, heartbeats, starts execution, completes or fails, and records audit/lineage for supported outputs. `WorkerRuntimeService` enforces lease ownership and terminal transitions. This is aligned with Mission-Based AI's governed execution layer. |
| Evidence | Partial foundation. | `backend/domain/lineage_record.py`, `backend/services/worker_runtime_service.py`, `backend/domain/audit_event.py`, `backend/domain/governance_event.py`, `artifacts/validation/README.md` | Evidence exists as audit/governance events, validation artifacts, and lineage output when handlers opt into persisted output. There is no mission-level `EvidenceItem` model, evidence sufficiency rubric for product outcomes, or evidence-to-success-criteria mapping. |
| Outcome review | Missing. | `backend/domain/enums.py`, `backend/runtime/state_machine.py` | Runtime terminal states exist, but mission outcome review does not. There is no `OutcomeReview`, confidence score, success/failure rationale, operator approval loop, or recommended next action layer. |
| Memory | Missing. | No production memory model found in required paths/searches. | The product direction names `MemoryCandidate` and memory promotion, but the repository does not yet have a first-class memory capture, review, retention, tenant isolation, or promotion path. |
| Governance/runtime | Strong foundation. | `backend/services/runtime_governor.py`, `backend/services/policy_guardian.py`, `backend/services/execution_coordinator.py`, `backend/services/runtime_maintainer.py`, `docs/validation/live-runtime-matrix.md`, `docs/validation/live-runtime-proof-release-gate.md` | The lower governed runtime is the repository's strongest alignment point: auth/tenant boundaries, policy-gated queue admission, queue/lease state authority, recovery, dead-letter behavior, observability, and release validation are documented and implemented. |

## 3. Missing top-layer pieces

### Missing product concepts

These should be added above the runtime foundation:

1. **Mission intake contract** — a route/service/schema that accepts an outcome in business language and captures constraints, priorities, success criteria, budgets, approvals, allowed tools, and risk tolerance.
2. **Mission plan model** — explicit `MissionPlan` records with planner rationale, plan status, versioning, operator edits, approval state, and linkage to the originating mission.
3. **Task graph model** — explicit graph nodes/edges/dependencies, ordering rules, concurrency constraints, graph validation, graph versioning, and operator visualization/editing.
4. **Capability registry product model** — declared capabilities/modules with input/output schemas, permissions, risk level, evidence produced, approval requirements, handler mapping, tenant/plan enablement, and lifecycle status.
5. **Evidence item model** — mission-scoped evidence with source, task/capability provenance, confidence, freshness, retention class, and relation to success criteria.
6. **Outcome review model** — structured review that decides whether the mission achieved the outcome, what evidence supports that decision, what failed, and what next action is recommended.
7. **Memory candidate and promotion flow** — explicit candidate creation, review, tenant isolation, retention policy, provenance, and controlled promotion into reusable memory.
8. **Operator transparency APIs** — read paths exposing plan, graph, capability selection, queue/lease/retry state, evidence, audit trail, validation artifacts, and memory decisions in mission-centered form.

### Missing runtime concepts

These should come after the product contracts are explicit:

1. **Planner execution service** that converts mission intake into a plan without bypassing governance.
2. **Task graph materializer** that creates execution tasks and graph dependencies transactionally.
3. **Capability dispatch bridge** that maps capability registry entries to concrete worker handlers without arbitrary task-type execution.
4. **Capability schema enforcement** at queue admission and handler dispatch.
5. **Evidence capture hooks** standardized across capabilities, not only optional handler output lineage.
6. **Outcome-review runner** that evaluates completed task graphs against mission success criteria.
7. **Memory promotion runner** gated by outcome review, tenant policy, and approval rules.
8. **Validation scenarios for mission outcomes** proving mission intake-to-outcome behavior, not only low-level queue/lease mechanics.

## 4. Placeholder/mock/fake risk

| Item | Classification | Evidence from review | Risk assessment |
|---|---|---|---|
| `TaskHandler` registration and dispatcher registry | Safe abstract interface | `register_handler()` validates task types and registers callables; dispatcher enforces handler result shape. | Safe as an extension point. It becomes insufficient only if treated as a capability registry replacement. |
| `echo` handler | Validation-only behavior | `echo_handler` persists proof-of-work output and is used by live/integration proof paths. | Safe for runtime proof. It should not be sold as a real business capability. |
| `force_fail` handler | Validation-only behavior | `force_fail_handler` intentionally raises for runtime validation. | Safe if retained as seeded validation behavior and not exposed as a normal tenant capability. |
| Unit-test mocks/fakes/MagicMocks | Test-only behavior | Tests patch repositories/services, use fake curl, fake health checkers, fake auth services, and MagicMocks. | Safe test isolation pattern. Not a production concern by itself. |
| `docs_only` matrix row `EX-03` | Documentation-only validation gap | Matrix marks mixed mission queue outcomes as `documented` / `docs_only`. | Safe as an honest matrix classification; risky only if interpreted as implemented proof. |
| `not_executed` artifacts for integration-backed rows | Validation-only behavior | Matrix and artifact docs explicitly state these are pointers to integration proof, not fresh runner evidence. | Safe because the docs distinguish provenance. Should remain visible until runner-backed proof exists. |
| `default_handler` | Production-risk placeholder | The dispatcher docstring says to replace `default_handler` with real AI agent dispatch; the handler logs metadata and returns completed status. Unknown task types fall back to default when present. | Highest coherence risk. In production, an unrecognized or under-specified task can be marked completed without meaningful mission work or evidence. This is acceptable only as a temporary runtime scaffold, not as Mission-Based AI behavior. |

## 5. Validation matrix alignment

The validation matrix supports Mission-Based AI by proving the governed runtime layer that mission execution must rely on:

- tenant-scoped work admission and protected route behavior;
- queue/state/lease transitions;
- worker execution and completion;
- failure, retry, recovery, and dead-letter behavior;
- audit/governance and validation artifact evidence;
- release-gating semantics that separate run outcome from evidence sufficiency.

That is the right foundation. Mission-Based AI should not weaken these rows or bypass them.

However, the matrix currently proves mostly runtime mechanics rather than product mission outcomes. A queue admission row can prove that a task moved safely into runtime; it does not prove that a human outcome was decomposed correctly, that success criteria were met, that evidence supports the outcome, or that memory promotion is justified.

Specific alignment observations:

- The matrix language is honest that it is a governed runtime validation contract.
- Evidence sources are strong for API/DB/Redis/audit/worker logs, but not yet for mission-level `EvidenceItem` or `OutcomeReview` records.
- `EX-03` explicitly recognizes mixed mission queue outcomes, but it is `docs_only`; this is a useful marker for where mission-level validation should mature.
- `not_executed` integration-backed rows are correctly described as pointers, not live-runner proof.
- No matrix row yet validates mission intake, planning quality, task graph correctness, capability selection, outcome review, or memory promotion.

No matrix rows should be deleted or rewritten for this pass. The next step is to add mission-outcome validation rows once the product models and APIs exist.

## 6. Recommended implementation sequence

### PR 1 — Mission product contracts and schemas

- **Purpose:** Define mission intake, constraints, success criteria, and operator-facing mission detail contracts without changing runtime execution.
- **Files likely touched:** `backend/domain/mission.py`, new schemas under `backend/schemas/` if that pattern exists, `backend/api/routes/mission.py`, repository/service tests, docs.
- **Tests needed:** unit/contract API tests for mission intake validation, tenant isolation, quota/plan interactions if intake creates records; no worker integration required unless queueing changes.
- **Risk level:** Medium.
- **Why before next PR:** Planning and graph generation need a stable mission intake and success-criteria contract.

### PR 2 — Mission plan model and operator review surface

- **Purpose:** Add `MissionPlan` as a first-class, versioned, reviewable product object.
- **Files likely touched:** new domain/repository/service/API files, Alembic migration, route tests, state-machine tests if plan states are formalized.
- **Tests needed:** unit tests for plan lifecycle; contract tests for create/read/update/approve; tenant isolation tests.
- **Risk level:** Medium-high because it introduces persistence.
- **Why before next PR:** A task graph should materialize from an approved/accepted plan, not directly from raw user text.

### PR 3 — Task graph model without runtime dispatch changes

- **Purpose:** Represent graph nodes, edges, dependencies, ordering, and graph validation separately from existing `ExecutionTask` queue execution.
- **Files likely touched:** new graph domain/repository/service/API files, migrations, docs, tests.
- **Tests needed:** graph validation unit tests, cycle detection, tenant isolation, graph-to-task mapping contract tests.
- **Risk level:** High due to data-model and correctness implications.
- **Why before next PR:** Capability selection needs graph nodes and task semantics to attach to.

### PR 4 — Capability registry as product/control-plane metadata

- **Purpose:** Add a registry describing capabilities, schemas, permissions, risk, approvals, evidence, handler mapping, and tenant/plan enablement.
- **Files likely touched:** new capability domain/repository/service/API files, docs, tests; avoid changing dispatcher behavior except import/reference alignment if needed.
- **Tests needed:** schema validation, duplicate capability prevention, tenant/plan filtering, risk/approval metadata tests.
- **Risk level:** Medium.
- **Why before next PR:** Runtime dispatch should only be wired after capabilities are declared and governable.

### PR 5 — Planner-to-graph materialization

- **Purpose:** Convert an approved mission plan into a validated task graph and planned execution tasks while preserving existing queue authority.
- **Files likely touched:** planner/materializer service, mission/plan/graph repositories, `ExecutionTaskRepository`, route/service tests.
- **Tests needed:** transactionality, rollback on invalid graph, tenant isolation, idempotency, no queue admission until explicit queue step.
- **Risk level:** High.
- **Why before next PR:** Evidence and outcome review depend on a stable mission graph and task provenance.

### PR 6 — Evidence item model and capability output contract

- **Purpose:** Standardize mission-level evidence capture and link evidence to tasks, capabilities, success criteria, audit, and lineage.
- **Files likely touched:** new evidence domain/repository/service/API files, `WorkerRuntimeService` only if adding documented evidence-output hooks, tests, docs.
- **Tests needed:** evidence creation, provenance integrity, tenant isolation, output schema enforcement, lineage compatibility.
- **Risk level:** Medium-high.
- **Why before next PR:** Outcome review must evaluate evidence, not raw task completion alone.

### PR 7 — Outcome review service

- **Purpose:** Add mission outcome review that compares mission success criteria against evidence and task graph status.
- **Files likely touched:** new outcome review domain/repository/service/API files, mission status transitions, docs, tests.
- **Tests needed:** successful/failed/partial outcome cases, insufficient evidence, human approval gates, tenant isolation.
- **Risk level:** Medium-high.
- **Why before next PR:** Memory promotion must be gated by reviewed outcomes.

### PR 8 — Memory candidate and promotion flow

- **Purpose:** Add controlled memory candidates and approvals after outcome review.
- **Files likely touched:** new memory domain/repository/service/API files, policy/retention docs, tests.
- **Tests needed:** candidate creation, approval/rejection, tenant isolation, retention/provenance, no promotion without outcome review.
- **Risk level:** High due to data retention and privacy implications.
- **Why after prior PRs:** Memory should be a consequence of evidence-backed outcomes, not an ungoverned side effect.

### PR 9 — Runtime dispatch hardening around capabilities

- **Purpose:** Replace default-handler production fallback with explicit capability/handler resolution while preserving validation handlers in controlled contexts.
- **Files likely touched:** `backend/workers/task_dispatcher.py`, capability service, worker tests, runtime integration tests, validation docs if proof setup changes.
- **Tests needed:** unknown capability fails closed, validation `echo` remains available for proof fixtures, `force_fail` remains validation-scoped, handler output schema enforcement, lease release/failure behavior.
- **Risk level:** High because it touches runtime behavior.
- **Why after capability registry:** Removing default fallback safely requires declared capability metadata and migration path.

### PR 10 — Mission-outcome validation matrix expansion

- **Purpose:** Add validation rows and artifacts for mission intake, plan approval, graph materialization, capability selection, evidence sufficiency, outcome review, and memory promotion.
- **Files likely touched:** `docs/validation/live-runtime-matrix.md`, `artifacts/validation/README.md`, validation runner scripts only when implementing runnable proof, tests.
- **Tests needed:** runner unit tests for new rows/provenance; integration tests for mission outcome paths; docs/provenance tests.
- **Risk level:** Medium.
- **Why last:** The matrix should prove implemented truth, not lead with aspirational rows beyond honest `documented` status.

## 7. Non-goals

Do not change these yet:

- backend runtime behavior;
- validation runner logic;
- migrations;
- queue adapter semantics;
- worker lease, retry, recovery, or dead-letter behavior;
- `RuntimeMaintainer` recovery rules;
- `WorkerRuntimeService` state transition semantics;
- release-gating matrix rows;
- placeholder code removal before capability registry and migration path exist;
- mission-outcome validation rows before product/runtime models exist.

For this pass, documentation alignment is the correct scope.

## 8. PRIDE self-audit

### Files read

Required files read:

- `README.md`
- `docs/product/mission-based-ai-core.md`
- `docs/PROJECT_STATE_REPORT.md`
- `docs/SAAS_ARCHITECTURE.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`
- `artifacts/validation/README.md`
- `backend/workers/task_dispatcher.py`
- `backend/services/worker_runtime_service.py`
- `backend/services/runtime_maintainer.py`
- `backend/api/routes/mission.py`
- `backend/api/routes/task.py`

Additional implementation files read because `backend/models/mission.py` and `backend/models/execution.py` are not present:

- `backend/domain/mission.py`
- `backend/domain/execution_task.py`
- `backend/services/mission_executor.py`
- `backend/services/execution_coordinator.py`
- `backend/repositories/mission_repository.py`
- `backend/repositories/execution_task_repository.py`

Test discovery/read coverage:

- Discovered mission/task/worker/runtime tests with `rg --files tests backend | rg '(test|tests).*(mission|task|worker|runtime)|(mission|task|worker|runtime).*(test|tests)'`.
- Reviewed search hits across unit, contract, and integration tests for mission, task, worker, runtime, `echo`, `force_fail`, mocks/fakes, `docs_only`, and `not_executed` usage.

### Searches performed

Required search terms were run across repository docs, backend, scripts, workflows, artifacts, and tests:

- `mission`
- `Mission`
- `task graph`
- `outcome`
- `evidence`
- `memory`
- `capability`
- `module`
- `worker`
- `default_handler`
- `echo`
- `force_fail`
- `placeholder`
- `mock`
- `fake`
- `docs_only`
- `not_executed`

### Limits

- `PROJECT_SPEC.md` was requested by session instructions but is not present in this checkout.
- The checkout has no configured git remote in this environment, so there was no remote `main` to pull from. Work was performed on the current branch containing the Mission-Based AI core document.
- This was a docs-only coherence pass. Runtime tests were not required because no runtime code, validation runner logic, or migrations were changed.

### Confidence

**Confidence: high for repository coherence direction; medium-high for exhaustive test interpretation.**

The core verdict is strongly supported by the required docs and runtime files: the governed runtime foundation is real, while mission intake/planning/task graph/capability/evidence/outcome/memory product systems are mostly absent or partial. Test interpretation is medium-high because the repository contains broad test coverage and the review used search/read passes rather than executing all runtime/integration tests.
