# Mission Runtime Architecture Map

Status: audit-grounded architecture reference  
Scope: mission runtime, queue authority, declarative contract lanes, provider boundaries, live egress action surfaces  
Purpose: prevent future implementation work from mistaking intentional architecture boundaries for gaps.

## Executive summary

Ajenda has a real runtime core.

The system is not only declarative contracts, planning documents, or placeholder routes. The active runtime path is queue-backed and worker-dispatched:

Route / service admission  
→ `ExecutionCoordinator`  
→ `QueueAdapter`  
→ `WorkerRuntimeService`  
→ `WorkerLoop`  
→ `TaskDispatcher`  
→ task handler / `tool.invoke`  
→ `ActionRegistry` / action handler  
→ `WorkerRuntimeService.complete()` or `WorkerRuntimeService.fail()`  
→ lineage / evidence / audit  
→ queue complete / fail / release

The system also has intentional non-runtime lanes. These include declarative contracts, read models, staged mission bridge routes, and future provider boundaries. These should not be treated as bugs merely because they do not execute work.

The intelligence lane includes one bounded post-commit coordinator. After
EvidenceBridge durability, `TemporalIntelligenceAdvancementService` decides only
whether canonical Outcome evidence may schedule Decision Episode materialization,
or canonical DecisionLearningSignal evidence may schedule Experience consolidation.
It creates no mission graph node and queues no business action. Successors enter
through `ExecutionCoordinator` and retain queue, lease, dispatcher, action-owner,
tenant, provenance, and evidence authority.

Temporal Composition coordinates existing intelligence authorities and determines
transition eligibility. It does not own Decision, Outcome, Experience, Knowledge,
mission planning, or execution semantics.

Mission queue authority is consolidated in `MissionRuntimeQueueAdmissionService.admit()`. `POST /v1/missions/{mission_id}/runtime-queue-admission` is the canonical API entrypoint, not a second authority. `POST /v1/missions/{mission_id}/queue` remains only as a deprecated compatibility adapter: it invokes the same service, persists the same admission metadata through that service, and projects only the legacy three-field response.

## Classification vocabulary

Use these terms in future audits and PRs.

| Classification | Meaning |
|---|---|
| True runtime | Executes or directly advances executable work through queue, lease, dispatcher, handler, completion, evidence, or recovery. |
| Governed runtime mutation | Mutates runtime-adjacent state, but does not execute handlers. Example: creating planned execution tasks or activating worker leases. |
| Declarative contract lane | Persists contracts, metadata, review records, profiles, evidence records, or governance requests without executing runtime work. |
| Read model / false runtime by name | Uses runtime language but only reads or previews state. It must not mutate task, queue, lease, dispatcher, or handler state. |
| Future-facing provider boundary | Defines external provider or credential contracts but does not make live provider calls yet. |
| Live egress action surface | A runtime tool/action path that can make outbound network or delivery calls, such as HTTP or webhook actions. |
| Drift candidate | A path with overlapping meaning or unclear ownership that needs reconciliation before extension. |


## Subsystem lane contract chains

This section defines the fourteen subsystem lanes used for future Ajenda implementation passes. It is subordinate to the authority ledger: these lane definitions explain how to read and extend existing `authority_entries`; they do not create a fifth authority class, a parallel registry, or execution permission outside the four canonical authority classes (`declarative`, `read_model`, `governed_mutation`, `runtime_authoritative`). When implementation, tests, and this map disagree, trace implementation and proofs first, then correct the stale contract surface.

### 1. Tenant/Auth/Security boundary

- **Purpose:** Fail-closed tenant, principal, permission, policy, API-key, and cross-tenant protection layer that every other lane depends on.
- **Current status:** live, with route/service proof for auth and API-key surfaces; policy outcomes are additionally proven through runtime coordinator tests where applicable.
- **Authority layer(s):** `read_model` for identity reads; `governed_mutation` for API-key lifecycle and tenant-scoped security mutations; policy checks gate `runtime_authoritative` admission paths but do not by themselves grant runtime authority.
- **Source-of-truth files:** `backend/middleware/auth_context.py`, `backend/api/routes/auth.py`, `backend/api/routes/api_keys.py`, `backend/services/api_key_service.py`, `backend/services/execution_coordinator.py`, `docs/contracts/authority-ledger.v1.yaml`.
- **Entry points:** `/v1/auth/*`, `/v1/api-keys/*`, `get_request_tenant_id`, tenant DB/session dependencies, `require_route_permission()`, API-key service methods, and coordinator policy/governor checks.
- **Allowed effects:** authenticate/identify principals, enforce tenant context, read identity claims, create/revoke tenant-scoped API keys under authorization/quota rules, and deny or hold runtime admission before side effects.
- **Forbidden effects:** cross-tenant mutation, tenant-context bypass, treating API-key or principal identity as runtime authority by itself, weakening fail-closed auth/policy behavior, or allowing read-model routes to mutate.
- **Contract chain:** request tenant context -> authentication/principal resolution -> route permission/scope check -> service/repository tenant filter -> policy/governor admission where runtime work is requested -> audit/governance outcome where the owning lane requires it.
- **Runtime boundary:** security gates runtime; it does not enqueue, claim, start, dispatch, or execute by itself.
- **Tenant/auth/policy requirements:** every route and downstream service must validate tenant scope before reads/writes; permission denial must occur before side effects; policy denial/pending-review must be preserved as first-class outcomes.
- **Evidence/audit requirements:** API-key lifecycle and policy/governance paths must emit the evidence/audit required by their ledger entries; identity reads remain read-only.
- **Failure/recovery semantics:** fail closed on missing tenant, mismatched tenant, missing/invalid principal, missing permission, invalid API-key scope, or policy denial.
- **Existing tests/proofs:** `tests/contract/test_auth_contract.py`, `tests/contract/api/test_auth_routes.py`, `tests/contract/api/test_api_key_routes.py`, `tests/unit/services/test_execution_coordinator_policy_denial_contract.py`, `tests/unit/services/test_execution_coordinator_policy_review_contract.py`.
- **Missing proof, if any:** keep expanding repository/service tenant-filter tests and side-effect pre-denial tests for each new mutation lane.
- **Pitfalls to avoid:** treating auth as route middleware only, allowing downstream services to assume tenant correctness without proof, allowing read-model routes to mutate, or letting declarative records imply execution authority.
- **Must-read before modification:** all source-of-truth files above plus the listed tests.

### 2. Mission intake layer

- **Purpose:** Tenant-scoped entry point that captures business/user mission intent and creates mission records plus intake metadata.
- **Current status:** live governed mutation.
- **Authority layer(s):** `governed_mutation`.
- **Source-of-truth files:** `backend/api/routes/mission.py`, `backend/services/mission_executor.py`, `docs/contracts/authority-ledger.v1.yaml`, `docs/product/mission-runtime-architecture-map.md`.
- **Entry points:** `POST /v1/missions` and mission-intake schema/model helpers in `backend/api/routes/mission.py`.
- **Allowed effects:** create tenant-owned mission rows and persist versioned intake envelope metadata.
- **Forbidden effects:** direct enqueue, execution-task materialization, worker dispatch, tool invocation, queue adapter calls, or tenant/auth envelope bypass.
- **Contract chain:** tenant/auth permission -> mission create request validation -> mission repository persistence -> intake metadata readback; runtime starts only in later bridge lanes.
- **Runtime boundary:** intake stops at mission/intake persistence and must not enter queue, worker, dispatcher, or tool runtime.
- **Tenant/auth/policy requirements:** tenant-owned mission creation with fail-closed permission and tenant mismatch behavior.
- **Evidence/audit requirements:** persist intake metadata; do not synthesize runtime evidence.
- **Failure/recovery semantics:** invalid intake or unauthorized/mismatched tenant fails before persistence or side effects.
- **Existing tests/proofs:** `tests/unit/api/test_mission_intake_route.py`, `tests/unit/domain/test_mission_intake_metadata.py`, authority-ledger coverage.
- **Missing proof, if any:** preserve no-runtime-call sentinels when future GTM mission creation is added.
- **Pitfalls to avoid:** collapsing create mission into run mission, secretly executing future GTM flows from creation, or treating intake as runtime authority.
- **Must-read before modification:** source-of-truth files and existing tests above.

### 3. Mission planning layer

- **Purpose:** Convert mission intent into durable plan meaning without runtime execution.
- **Current status:** live declarative contract with durable repository proof; still partial for broader autonomous planner/provider behaviors.
- **Authority layer(s):** `declarative`.
- **Source-of-truth files:** `backend/api/routes/mission.py`, `backend/repositories/mission_plan_repository.py`, `docs/contracts/authority-ledger.v1.yaml`, this architecture map.
- **Entry points:** `/v1/missions/{mission_id}/plan` route handlers and mission-plan repository operations.
- **Allowed effects:** create/update/read tenant-scoped plan contracts, phases, steps, metadata, and versioned plan details.
- **Forbidden effects:** queueing tasks, creating worker leases, calling `TaskDispatcher`, invoking tools/providers, or treating plan existence as execution approval.
- **Contract chain:** mission intent -> plan contract validation -> durable mission plan repository -> task graph may reference plan meaning in a later lane -> runtime bridge remains separate.
- **Runtime boundary:** planning is non-runtime and cannot grant provider/tool/queue authority.
- **Tenant/auth/policy requirements:** mission and plan reads/writes must stay tenant-scoped and permission-gated.
- **Evidence/audit requirements:** plan metadata is contract evidence only; no runtime evidence is emitted.
- **Failure/recovery semantics:** malformed/version-incompatible plan metadata fails closed instead of being guessed into runtime meaning.
- **Existing tests/proofs:** `tests/unit/api/test_mission_planning_contract.py`, `tests/unit/repositories/test_mission_plan_repository.py`, `tests/unit/db/test_mission_plan_migration_contract.py`.
- **Missing proof, if any:** stronger explicit plan-to-task-graph relationship tests should accompany future planner expansion.
- **Pitfalls to avoid:** mixing planner output with queue admission, using unversioned metadata, or allowing plans to imply provider/tool authorization.
- **Must-read before modification:** mission route plan sections, mission-plan repository, ledger entry, and listed tests.

### 4. Task graph / declarative contract layer

- **Purpose:** Normalized declarative graph of intended work; defines work shape, dependencies, node metadata, provenance, validation, and materialization references without executing.
- **Current status:** live declarative contract with a bounded governed cleanup path for superseded planned materialized tasks.
- **Authority layer(s):** `declarative`; bounded cleanup uses `governed_mutation` semantics and UPG/runtime-state review.
- **Source-of-truth files:** `backend/api/routes/mission.py`, `docs/contracts/authority-ledger.v1.yaml`, this architecture map, task-graph contract/migration tests.
- **Entry points:** `/v1/missions/{mission_id}/task-graph`, graph metadata helpers, materialization-reference helpers, and superseded planned-task cleanup helpers in `backend/api/routes/mission.py`.
- **Allowed effects:** persist graph contract and metadata; supersede graph metadata; cancel only superseded planned materialized tasks where the implemented cleanup path explicitly allows it.
- **Forbidden effects:** enqueueing, dispatching, creating leases, invoking tools, silently mutating queued/claimed/running/completed runtime tasks, or treating graph nodes as execution tasks.
- **Contract chain:** mission plan/intent -> task graph contract -> graph materialization metadata -> runtime task materialization later creates `PLANNED` execution tasks -> queue admission later enqueues.
- **Runtime boundary:** graph creation is not execution; cleanup is bounded to planned materialized tasks and must not cross into active runtime.
- **Tenant/auth/policy requirements:** graph operations must remain tenant-scoped and permission-gated through mission ownership.
- **Evidence/audit requirements:** graph metadata/provenance proves declared shape; no runtime evidence is emitted.
- **Failure/recovery semantics:** version/metadata drift fails closed; cleanup must not make stale graph materializations executable.
- **Existing tests/proofs:** `tests/unit/domain/test_mission_task_graph_contract_metadata.py`, `tests/contract/api/test_task_graph_runtime_boundary_contract.py`, `tests/integration/runtime/test_task_graph_runtime_admission_real.py`.
- **Missing proof, if any:** keep strengthening replacement cleanup invariants when graph cleanup behavior changes.
- **Pitfalls to avoid:** treating graph nodes as executable tasks, letting replacement become runtime execution, or allowing unversioned metadata drift.
- **Must-read before modification:** mission task-graph sections in `backend/api/routes/mission.py`, ledger entry, architecture map, and listed tests.

### 5. Mission-to-runtime bridge

- **Purpose:** Staged bridge that moves mission meaning toward runtime without collapsing materialization, queue admission, claim, start, and run authority.
- **Current status:** live/partial staged bridge; compatibility `/queue` remains live convenience behavior but is not canonical staged admission.
- **Authority layer(s):** `read_model`, `governed_mutation`, and `runtime_authoritative` depending on method/stage.
- **Source-of-truth files:** `backend/api/routes/mission.py`, `backend/services/mission_runtime_queue_admission_service.py`, `backend/services/mission_executor.py`, `backend/services/execution_coordinator.py`, `docs/contracts/authority-ledger.v1.yaml`, this architecture map.
- **Entry points:** readiness/preview/readback GET routes; POST runtime-task-materialization; POST runtime-queue-admission; POST worker-claim/start/run admission; compatibility `POST /v1/missions/{mission_id}/queue`.
- **Allowed effects:** each POST performs only its bounded stage; GET/readiness routes aggregate/read only; compatibility `/queue` delegates to `MissionRuntimeQueueAdmissionService.admit()`, so it queues only current materialized planned tenant tasks through `ExecutionCoordinator` and persists the same staged admission metadata before projecting the legacy response.
- **Forbidden effects:** all-in-one runtime collapse, queue authority bypass, lease authority bypass, dispatch from preview/readback routes, or turning compatibility `/queue` into a second runtime engine.
- **Contract chain:** graph -> materialization -> runtime queue admission -> worker claim -> worker start -> worker run/dispatcher; every stage has separate ledger and route/service ownership.
- **Runtime boundary:** only queue admission and run admission enter true runtime; materialization/claim/start are governed mutations; readbacks are read-only.
- **Tenant/auth/policy requirements:** permission and tenant scope must be enforced at each stage; queue admission must preserve governor/policy outcomes.
- **Evidence/audit requirements:** staged metadata/receipts/blockers must be persisted by owning stages; runtime evidence appears only after true runtime execution.
- **Failure/recovery semantics:** blockers, warnings, denied, pending-review, already-admitted, and idempotent readback outcomes are valid contract results, not generic errors.
- **Existing tests/proofs:** `tests/contract/api/test_mission_queue_contract.py`, `tests/contract/api/test_task_queue_contract.py`, `tests/integration/runtime/test_task_graph_runtime_admission_real.py`.
- **Missing proof, if any:** continue adding per-stage no-side-effect and repeated-run tests as stage behavior grows.
- **Pitfalls to avoid:** calling everything runtime, treating preview/readback as authority, or confusing `/queue` compatibility with canonical staged admission.
- **Must-read before modification:** source-of-truth files and listed tests.

### 6. Runtime task materialization

- **Purpose:** Governed mutation that converts approved/current graph meaning into tenant-owned `PLANNED` `ExecutionTask` rows.
- **Current status:** live governed mutation.
- **Authority layer(s):** `governed_mutation`; GET readback is `read_model`.
- **Source-of-truth files:** `backend/api/routes/mission.py`, `backend/services/mission_runtime_task_materialization_service.py`, execution task repository/domain files, `docs/contracts/authority-ledger.v1.yaml`, this architecture map.
- **Entry points:** `POST /v1/missions/{mission_id}/runtime-task-materialization` and `GET /v1/missions/{mission_id}/runtime-task-materialization`.
- **Allowed effects:** create only current tenant-scoped `PLANNED` execution tasks with graph/materialization references; persist materialization receipts and blockers.
- **Forbidden effects:** enqueueing, dispatching, creating/activating leases, completing/failing work, materializing stale graph nodes, or creating queued/running tasks directly.
- **Contract chain:** current task graph/materialization metadata -> `PLANNED` execution tasks -> runtime queue admission later decides queue state.
- **Runtime boundary:** materialization writes execution-task rows but does not enter queue or handler runtime.
- **Tenant/auth/policy requirements:** materialized tasks must match mission tenant and current graph/materialization scope.
- **Evidence/audit requirements:** materialization metadata and task metadata preserve graph node mappings; no runtime evidence is emitted.
- **Failure/recovery semantics:** idempotency/duplicate prevention, stale-scope blockers, and bounded cleanup/cancel behavior must remain explicit.
- **Existing tests/proofs:** `tests/integration/runtime/test_task_graph_runtime_admission_real.py`, `tests/contract/api/test_task_graph_runtime_boundary_contract.py`, authority-ledger materialization entries.
- **Missing proof, if any:** add or preserve narrow tests for idempotency, duplicate prevention, and stale graph non-materialization when changed.
- **Pitfalls to avoid:** creating queued/running tasks directly, losing graph node mapping, non-idempotent materialization, or leaving old graph materializations executable.
- **Must-read before modification:** route materialization helpers, materialization service, execution task repository/domain, architecture map, and listed tests.

### 7. Queue admission / coordinator authority

- **Purpose:** Shared authority gate that decides whether planned work may enter queue state, be denied, enter pending review, or fail admission safely.
- **Current status:** live runtime-authoritative admission.
- **Authority layer(s):** `runtime_authoritative`.
- **Source-of-truth files:** `backend/services/execution_coordinator.py`, `backend/queue/base.py`, `backend/queue/local_adapter.py`, `docs/contracts/authority-ledger.v1.yaml`.
- **Entry points:** `ExecutionCoordinator.queue_task()`, `MissionRuntimeQueueAdmissionService.admit()`, `/v1/tasks/*` queue routes, and mission queue/admission routes. `MissionExecutor.queue_all_planned_tasks()` remains library code but has no supported mission API caller and is not a mission admission authority.
- **Allowed effects:** evaluate runtime governor/policy, move eligible planned tasks to queued, call `QueueAdapter.enqueue_task()`, persist denial/pending-review/queue outcomes and audit/governance events.
- **Forbidden effects:** bypassing `ExecutionCoordinator`, treating denial/pending-review as broken runtime, leaving false queued DB state after enqueue failure, direct route/service `QueueAdapter` calls outside explicit authority, or collapsing success/denial/review/failure into one result.
- **Contract chain:** planned task -> coordinator policy/governor -> DB queued transition and queue enqueue -> compensation on enqueue failure -> queued work becomes claimable.
- **Runtime boundary:** queue admission admits work but does not claim leases, start execution, or dispatch handlers.
- **Tenant/auth/policy requirements:** tenant-scoped task lookup and permission checks before queue admission; policy/governor outcomes fail closed.
- **Evidence/audit requirements:** denial, pending-review, queue success, and queue failure compensation must remain observable through state/audit/governance paths.
- **Failure/recovery semantics:** enqueue failure must compensate DB state; retries must avoid duplicate queue entries and preserve DB/queue consistency.
- **Existing tests/proofs:** `tests/unit/services/test_execution_coordinator.py`, `tests/unit/services/test_execution_coordinator_policy_denial_contract.py`, `tests/unit/services/test_execution_coordinator_policy_review_contract.py`, `tests/contract/api/test_task_queue_contract.py`.
- **Missing proof, if any:** keep adding queue-adapter failure compensation tests as adapters evolve.
- **Pitfalls to avoid:** equating “not queued” with error, hiding governed non-queue outcomes, duplicate entries on retry, or moving queue authority into route code.
- **Must-read before modification:** source-of-truth files and listed tests.

### 8. Queue adapter / queue state system

- **Purpose:** Durable/adapter-backed queue system that owns enqueue, claim, heartbeat, release, complete, fail, retry, and dead-letter mechanics.
- **Current status:** live local adapter plus abstract adapter contract; external/durable adapter expansion remains future work.
- **Authority layer(s):** `runtime_authoritative`.
- **Source-of-truth files:** `backend/queue/base.py`, `backend/queue/local_adapter.py`, `backend/services/runtime_maintainer.py`, `backend/services/worker_runtime_service.py`.
- **Entry points:** `QueueAdapter` methods, `LocalQueueAdapter`, `WorkerRuntimeService` queue calls, operations dead-letter/retry routes, runtime maintainer recovery paths.
- **Allowed effects:** enqueue/claim/heartbeat/release/complete/fail queue messages, maintain processing keys, move tasks to dead-letter, retry dead-letter payloads, and expose queue inspection under proper boundaries.
- **Forbidden effects:** DB state pretending enqueue success after queue failure, terminal queue acknowledgement before DB terminal truth commits, hidden retry/dead-letter loss, lease release/expiry contrary to runtime truth, or changing queue semantics to satisfy incorrect test assumptions.
- **Contract chain:** coordinator enqueue -> adapter queued state -> worker claim/processing lease key -> heartbeat -> DB terminal commit -> queue complete/fail/release -> retry/dead-letter/recovery as needed.
- **Runtime boundary:** adapter owns queue state, not DB mission/task truth; DB and queue state must be reconciled by owning services.
- **Tenant/auth/policy requirements:** queue payloads carry tenant/task scope and must be consumed only through tenant/runtime-authoritative services.
- **Evidence/audit requirements:** retry/dead-letter and terminal cleanup failures must remain visible to operations/recovery surfaces.
- **Failure/recovery semantics:** stale claim/start recovery, processing cleanup, retry/dead-letter, and terminal ack failure behavior must be explicit; `EXPIRED` vs `RELEASED` semantics must follow runtime truth.
- **Existing tests/proofs:** `tests/unit/workers/test_worker_loop_contracts.py`, `tests/integration/runtime/test_claim_start_failure_recovery_real.py`, queue/coordinator tests.
- **Missing proof, if any:** stronger adapter-specific terminal ack failure tests are required before claiming complete durable queue coverage.
- **Pitfalls to avoid:** forcing tests to match assumptions, using `RELEASED` where runtime truth is `EXPIRED`, queue/DB split-brain, or hidden duplicate execution after ack failure.
- **Must-read before modification:** source-of-truth files and listed tests.

### 9. Worker lease lifecycle

- **Purpose:** Authority system for claim/start/run ownership; runtime execution requires valid lease ownership.
- **Current status:** live runtime-authoritative lifecycle with governed claim/start bridge stages.
- **Authority layer(s):** `governed_mutation` for claim/start admission stages; `runtime_authoritative` for worker runtime execution and recovery.
- **Source-of-truth files:** `backend/services/worker_runtime_service.py`, `backend/workers/worker_loop.py`, `backend/domain/worker_lease.py`, `backend/services/runtime_maintainer.py`.
- **Entry points:** `WorkerRuntimeService.claim_next_task()`, `start_execution()`, `heartbeat()`, `release()`, runtime maintainer stale-lease paths, worker claim/start admission routes/services.
- **Allowed effects:** create leases on claim, activate leases on start, heartbeat active leases, release recoverable unstarted claims, expire stale leases, and bind task execution to worker/lease identity.
- **Forbidden effects:** running without claimed/active lease, starting without valid claim authority, dispatch after completion, stale lease execution, or conflating expired/released/active/terminal meanings.
- **Contract chain:** queue claim -> worker lease created/owned -> start activates lease and task running -> dispatcher run requires active lease -> complete/fail releases or terminalizes lease/task.
- **Runtime boundary:** lease lifecycle grants execution ownership but handler dispatch still goes through worker runtime/dispatcher lane.
- **Tenant/auth/policy requirements:** lease/task tenant scope must match the claimed queue payload and runtime context.
- **Evidence/audit requirements:** claim/start/heartbeat/release/expire/complete/fail must preserve runtime evidence/audit required by worker runtime tests and ledger.
- **Failure/recovery semantics:** stale claims/starts are recoverable only through explicit release/expire/retry paths; no dispatcher re-entry after completion.
- **Existing tests/proofs:** `tests/unit/workers/test_worker_loop_contracts.py`, `tests/integration/runtime/test_claim_start_failure_recovery_real.py`, `tests/unit/services/test_worker_runtime_service_transaction_contract.py`.
- **Missing proof, if any:** preserve integration proof for each new adapter/recovery path.
- **Pitfalls to avoid:** treating queue claim alone as execution authority, worker loop bypass of `WorkerRuntimeService`, reclaim without processing cleanup, or expired/released semantic drift.
- **Must-read before modification:** source-of-truth files and listed tests.

### 10. Worker runtime / dispatcher execution

- **Purpose:** True runtime execution path from claimed/started work into handler execution, then complete/fail handling.
- **Current status:** live runtime-authoritative path.
- **Authority layer(s):** `runtime_authoritative`.
- **Source-of-truth files:** `backend/workers/worker_loop.py`, `backend/workers/task_dispatcher.py`, `backend/services/worker_runtime_service.py`, `backend/workers/handlers/tool_invoke.py`.
- **Entry points:** `WorkerLoop.run_forever()`, `WorkerLoop._claim_and_start_task()`, `TaskDispatcher.execute()`, registered task handlers, `WorkerRuntimeService.complete()` and `fail()`.
- **Allowed effects:** dispatch only lease-started tasks, heartbeat during handler execution, call registered handlers, persist task-output lineage, complete/fail DB terminal truth, and then perform queue terminal cleanup.
- **Forbidden effects:** dispatch without lease/start authority, complete/fail without matching runtime context, re-dispatch completed tasks, bypass worker runtime complete/fail, direct handler invocation from routes/services, or mixing handler failure with queue adapter failure semantics.
- **Contract chain:** worker loop claim/start -> dispatcher handler -> handler result validation -> worker runtime complete/fail -> lineage/evidence/audit -> queue complete/fail/release.
- **Runtime boundary:** all true handler execution must be inside this path; routes and declarative services must not invoke handlers directly.
- **Tenant/auth/policy requirements:** runtime context must match task, lease, worker actor, and tenant before terminal mutation.
- **Evidence/audit requirements:** completion/failure must preserve lineage, evidence bridge behavior, audit, and queue cleanup outcome visibility.
- **Failure/recovery semantics:** handler success followed by terminal queue failure must not overwrite committed DB terminal truth; ack failure handling must be explicit and retry-safe.
- **Existing tests/proofs:** `tests/unit/workers/test_worker_loop_contracts.py`, `tests/unit/workers/test_task_dispatcher_runtime_contract.py`, `tests/unit/workers/test_task_dispatcher_registry.py`, `tests/unit/services/test_worker_runtime_service_transaction_contract.py`.
- **Missing proof, if any:** strengthen queue terminal operation failure coverage whenever queue adapters change.
- **Pitfalls to avoid:** unsafe retry after completion failure, queue ack failure overwriting DB truth, route/service direct handler invocation, or runtime context drift.
- **Must-read before modification:** source-of-truth files and listed tests.

### 11. Tool/action runtime

- **Purpose:** Governed action execution layer under `tool.invoke`; registration is not execution authority and side effects require explicit runtime permission.
- **Current status:** lane complete for runtime authority over registered in-process/local proof actions and shared network egress authority for runtime HTTP/webhook tool actions; the canonical read-only external provider action (`provider.external_read`) is active for HTTPS GET/HEAD only through credential authority and network egress; OAuth, credential refresh, writes/sends/publishes, CRM/GTM mutations, and durable SaaS client fleets remain separate future lanes.
- **Authority layer(s):** `runtime_authoritative` for `tool.invoke`; related capability/adapter records remain `declarative`.
- **Source-of-truth files:** `backend/workers/handlers/tool_invoke.py`, `backend/services/tools/runtime_authority.py`, `backend/services/tools/action_registry.py`, `backend/services/tools/capability_validation.py`, `backend/services/tools/schemas.py`, `backend/services/network_egress.py`, `backend/services/tools/http_actions.py`, `backend/services/tools/provider_read_actions.py`, `backend/services/tools/webhook_actions.py`, `backend/services/webhook_dispatch.py`, `backend/services/tools/evidence_bridge.py`.
- **Entry points:** `tool_invoke_handler()` delegates to `ToolRuntimeAuthority`; `ActionRegistry.invoke()` validates registered handler input/output; default action registry builder in `action_registry.py`; capability authority validation helpers; HTTP/webhook action registrations.
- **Allowed effects:** execute known actions only from a queued/claimed/started `ExecutionTask`; enforce invocation schema, effective side-effect class, runtime side-effect authorization, concrete capability/adapter authority for side-effecting actions, tenant context, handler `ActionResult`, and scoped `EvidenceItem` output.
- **Forbidden effects:** treating registry presence or broad `tool.invoke` support as concrete action permission, weakening side-effect authorization, declarative capability/adapter/ability records becoming runtime bindings automatically, collapsing `EXTERNAL_READ`, `EXTERNAL_WRITE`, `EXTERNAL_SEND`, or `EXTERNAL_PUBLISH` into each other, provider direct calls to `WorkerRuntimeService.complete()`/`fail()`, or tenant/context bypass.
- **Contract chain:** execution task -> dispatcher `tool.invoke` -> `ToolRuntimeAuthority` -> action registry lookup -> invocation/schema validation -> capability/adapter/side-effect authority -> action handler/provider -> validated `ActionResult`/`EvidenceItem` -> worker runtime completion/failure -> lineage/evidence bridge/audit/queue result.
- **Runtime boundary:** actions/providers must not call worker runtime complete/fail or create parallel dispatcher/queue/lease systems.
- **Tenant/auth/policy requirements:** task tenant and invocation authority must match; side-effecting writes/sends/publishes require explicit versioned `execution_constraints.side_effect_authorization` and concrete capability/adapter authority for the canonical action.
- **Evidence/audit requirements:** successful actions return validated `ActionResult` with at least one scoped `EvidenceItem`; live egress must preserve effective side-effect classification and audit/evidence expectations.
- **Failure/recovery semantics:** unknown actions and malformed invocations fail closed before side effects; shared network egress destination safety fails closed; action failure returns controlled runtime failure through dispatcher without evidence/output secret leakage.
- **Existing tests/proofs:** `tests/unit/tools/test_action_registry.py`, `tests/unit/tools/test_capability_action_validation.py`, `tests/unit/tools/test_http_actions.py`, `tests/unit/tools/test_evidence_bridge.py`, `tests/unit/workers/test_tool_invoke_handler.py`, `tests/unit/architecture/test_authority_ledger_contract.py`, `tests/integration/runtime/test_worker_executes_tool_invoke_task_real.py`.
- **Missing proof, if any:** OAuth, durable third-party provider clients, provider-specific readback/idempotency tests, writes, sends, publishes, and CRM/GTM mutations are required before broader live third-party providers are claimed complete.
- **Pitfalls to avoid:** binding declarative records directly to runtime, treating future providers as live, mixing local/proof providers with external activation, or broadening side effects for convenience.
- **Must-read before modification:** source-of-truth files and listed tests.

### 12. Evidence / lineage / audit system

- **Purpose:** Proof system that records what happened, links runtime output to lineage/evidence/audit, and preserves tenant/task/mission scope integrity.
- **Current status:** live runtime evidence bridge and declarative Evidence API; audit policy differs by lane and must stay explicit.
- **Authority layer(s):** `runtime_authoritative` for runtime lineage/evidence/audit emitted by worker execution; `declarative` for Evidence API records.
- **Source-of-truth files:** `backend/services/tools/evidence_bridge.py`, `backend/api/routes/evidence.py`, `backend/domain/evidence.py`, `backend/domain/lineage_record.py`, `backend/services/worker_runtime_service.py`.
- **Entry points:** `WorkerRuntimeService.complete()`, `build_tool_action_evidence_records()`, Evidence API routes, lineage/audit repositories invoked by worker runtime.
- **Allowed effects:** persist task-output lineage, task completion/failure audit events, narrow completed `tool.invoke` evidence into tenant-owned `EvidenceRecord` rows, and declaratively create/update evidence/provenance records through Evidence API.
- **Forbidden effects:** making optional annotation metadata fatal after completed side-effecting work, weakening tenant/task/mission scope validation, turning Evidence API into runtime bridge, universal ingestion of arbitrary handler output, or inferring evidence from arbitrary outputs.
- **Contract chain:** dispatcher handler output -> worker runtime lineage record -> evidence bridge for completed `tool.invoke` output -> durable EvidenceRecord -> audit/governance release proof surfaces.
- **Runtime boundary:** runtime evidence bridge is narrow and post-handler; Evidence API is declarative and must not dispatch runtime work.
- **Tenant/auth/policy requirements:** evidence scope must match task tenant, task id, and mission when present; Evidence API must remain tenant-scoped.
- **Evidence/audit requirements:** runtime path metadata, materialization references, lease id, lineage id, and side-effect class must be preserved where emitted.
- **Failure/recovery semantics:** malformed required runtime evidence fails the runtime completion path; malformed optional annotations are dropped safely where implemented and must not cause duplicate external side effects.
- **Existing tests/proofs:** `tests/unit/tools/test_evidence_bridge.py`, Evidence API contract tests, worker runtime service tests, live-runtime proof audit/lineage checks.
- **Missing proof, if any:** add tests before broadening evidence ingestion beyond completed `tool.invoke` outputs.
- **Pitfalls to avoid:** retrying external side effects because optional evidence annotation failed, confusing Evidence API with runtime bridge, accepting cross-tenant evidence, or over-broad evidence ingestion.
- **Must-read before modification:** source-of-truth files and listed tests.

### 13. Declarative product/governance contract lanes

- **Purpose:** Non-runtime contract system for business profile, capability registry, capability adapters, outcome review, retrieval governance, evidence/provenance APIs, and related product/governance records.
- **Current status:** live declarative/read-model lanes with some future-facing provider/governance expansions.
- **Authority layer(s):** primarily `declarative`; `read_model` for Mission Brief and projections.
- **Source-of-truth files:** `backend/api/routes/business_profile.py` and related business-profile route modules, `backend/api/routes/capability.py`, `backend/api/routes/capability_adapter.py`, `backend/api/routes/evidence.py`, `backend/api/routes/outcome_review.py`, `backend/api/routes/retrieval_contract.py`, `docs/contracts/authority-ledger.v1.yaml`, this architecture map.
- **Entry points:** `/v1/business-profile*`, `/v1/capabilities*`, `/v1/capability-adapters*`, `/v1/evidence*`, `/v1/outcome-reviews*`, `/v1/retrieval-contracts*`, `/v1/mission-brief/draft`.
- **Allowed effects:** persist/validate declarative records, profile facts/suggestions/decisions, capability and adapter metadata, evidence/provenance records, outcome review decisions, and retrieval governance requests; Mission Brief may read/generate draft projections only.
- **Forbidden effects:** executing runtime work, dispatching handlers, implicit runtime binding from capability/adapter records, profile truth mutation without audit where policy requires it, or silently mixing audit policies across declarative lanes.
- **Contract chain:** tenant/auth -> declarative schema validation -> repository persistence/read model -> optional compatibility validation -> later runtime authority must separately validate capability/adapter authority before execution.
- **Runtime boundary:** declarative records may inform runtime validation but cannot queue, claim, start, run, or invoke tools.
- **Tenant/auth/policy requirements:** each route remains tenant-scoped and permission-gated; audit policy must be explicit per lane.
- **Evidence/audit requirements:** Business Profile mutations append audit events; other declarative lanes keep their current explicit audit policy until changed with tests.
- **Failure/recovery semantics:** malformed declarative records fail validation; compatibility failures do not execute runtime work.
- **Existing tests/proofs:** related business profile, capability, adapter, evidence, outcome review, retrieval, Mission Brief, and authority-ledger contract tests.
- **Missing proof, if any:** no-runtime-call sentinels should be added for any declarative lane before it gains runtime-adjacent fields.
- **Pitfalls to avoid:** contract exists becoming runtime authorized, provider declarations treated as live credentials, silent audit inconsistency, or declarative APIs calling runtime bridge.
- **Must-read before modification:** listed source-of-truth files, ledger entries, architecture map, and related contract tests.

### 14. Observability / validation / release-gate system

- **Purpose:** Proof and release-control system that keeps runtime truth, docs, contracts, tests, validation artifacts, and mounted routes aligned.
- **Current status:** live validation scripts and contract tests; live-runtime proof gate is manual/operator-triggered for prod-like Compose proof.
- **Authority layer(s):** `read_model` for metrics/status reads; validation/release governance is contract proof, not runtime execution authority.
- **Source-of-truth files:** `scripts/validation/contract_drift_check.py`, `scripts/validation/ability_rollout_contract_check.py`, `scripts/validation/migration_seed_contract_check.py`, `docs/validation/live-runtime-matrix.md`, `docs/validation/live-runtime-proof-release-gate.md`, `docs/policies/DOCS_FRESHNESS_POLICY.md`, `docs/contracts/authority-ledger.v1.yaml`.
- **Entry points:** validation scripts, authority-ledger tests, contract drift tests, runtime matrix, release gate workflow/script, metrics/readiness routes.
- **Allowed effects:** validate docs/router/ledger/test drift, expose metrics/readiness safely, run release-gate proof, and record dynamic validation artifacts outside static contract truth.
- **Forbidden effects:** docs claiming unproven behavior, runtime behavior changes without targeted proof, authority-ledger drift from mounted routes, optionalizing validation scripts for semantic changes, fake proof paths, or promotion when proof surfaces conflict.
- **Contract chain:** implementation change -> ledger/architecture/docs update -> targeted tests -> validation scripts -> runtime matrix/release gate proof where applicable -> PR handoff.
- **Runtime boundary:** validation observes/proves runtime; it must not become a runtime bypass or synthetic proof of unimplemented behavior.
- **Tenant/auth/policy requirements:** metrics/status surfaces must not expose sensitive tenant payloads; validation must preserve tenant-isolation proof requirements.
- **Evidence/audit requirements:** release decisions require cited tests, scripts, runner artifacts, runtime evidence, or documented non-goals; unsupported proof cannot satisfy release gates.
- **Failure/recovery semantics:** stale docs, missing proof, ledger/router drift, or conflicting evidence block or warn explicitly; hidden assumptions are not acceptable release proof.
- **Existing tests/proofs:** `tests/unit/architecture/test_authority_ledger_contract.py`, `tests/unit/validation/test_contract_drift_check.py`, validation scripts, live-runtime matrix, live-runtime proof gate.
- **Missing proof, if any:** stronger lane-shape validation could be added later, but broad ledger schema churn is intentionally deferred unless necessary.
- **Pitfalls to avoid:** green unit tests as full release proof, docs without tests, fake proof paths, README/ledger/router drift, or hiding behavior changes in docs-only PRs.
- **Must-read before modification:** source-of-truth files and listed tests.

## True runtime lane

The active worker runtime is real.

Canonical lane:

`ExecutionCoordinator`  
→ `QueueAdapter`  
→ `WorkerRuntimeService`  
→ `WorkerLoop`  
→ `TaskDispatcher`  
→ task handler / `tool.invoke`  
→ `WorkerRuntimeService.complete()` or `WorkerRuntimeService.fail()`  
→ lineage / evidence / audit / queue acknowledgement

Responsibilities:

- `ExecutionCoordinator` admits queue work and calls `ExecutionCoordinator.queue_task()`.
- `QueueAdapter` owns queue enqueue, claim, heartbeat, complete, fail, release, dead-letter, and retry operations.
- `WorkerRuntimeService` owns claim, heartbeat, start, complete, fail, release, lineage, evidence bridge, audit, and queue result handling.
- `WorkerLoop` claims and starts tasks through `WorkerRuntimeService`, then delegates execution to `TaskDispatcher`.
- `TaskDispatcher` executes registered task handlers and calls `WorkerRuntimeService.complete()` or `WorkerRuntimeService.fail()`.
- `tool.invoke` is a real dispatcher handler, not a theoretical contract.
- `ActionRegistry` resolves registered tool actions.
- Runtime evidence is persisted through the evidence bridge after successful tool execution.

## Runtime queue admission is more than enqueue

`ExecutionCoordinator.queue_task()` is not only a queue wrapper.

It also participates in runtime policy/governance outcomes. Queue admission can result in:

- admitted / enqueued work,
- denied work,
- pending-review work,
- audit or governance events.

Future tests and docs should treat these outcomes as first-class queue-admission results, not edge cases hidden behind enqueue.

## Queue and database compensation semantics

Worker runtime queue/DB operations include compensation behavior.

Important runtime truth:

- A queue claim can be released when the related database claim fails.
- Terminal queue operations occur after database state has been committed.
- Split-brain and retry safety depend on preserving this ordering.

Future failure-path tests should preserve this behavior.

## tool.invoke runtime

`tool.invoke` is true runtime.

It validates:

- tenant scope,
- invocation shape,
- registered action existence,
- side-effect class,
- side-effect runtime state,
- side-effect authorization where required,
- valid ability manifest rollout/proof contract,
- tenant-visible capability / adapter authority where applicable.

A registered `ActionDefinition` does not mean an action is freely executable. Registry presence is not execution authority.

For side-effecting actions, `tool.invoke` must preserve the rule that side effects require the proper runtime state and explicit authorization. External read/write/send/publish actions also require explicit promotion authority and exact adapter side-effect classification before runtime execution; `external_side_effect` is a legacy broad declaration and is not concrete authority for any external runtime class.

## Mission runtime bridge

The mission runtime bridge is staged. Do not collapse these stages into a single vague “runtime” concept.

| Stage | Classification | Meaning |
|---|---|---|
| Mission task graph | Declarative contract with governed cleanup mutation | Persists task graph contract and must not enqueue, dispatch, or execute handlers. When replacing a graph tied to an existing materialization, cleanup may cancel superseded planned materialized `ExecutionTask` rows, so runtime-state invariants and UPG gates still apply to that cleanup path. |
| Runtime task materialization | Governed runtime mutation | Creates `ExecutionTask` rows in `PLANNED` state only. It must not enqueue or dispatch. |
| Runtime queue admission | True queue runtime | Queues current materialized planned tasks through `ExecutionCoordinator`. It must not create execution task rows or dispatch workers. |
| Worker claim admission | Governed runtime mutation | Creates worker leases and moves queued tasks to claimed. It must not start execution or dispatch handlers. |
| Worker start admission | Governed runtime mutation | Activates lease and moves claimed task to running. It must not dispatch handlers. |
| Worker run admission | True runtime execution | Claims queue payload and executes through `TaskDispatcher`. Repeated calls after completion must not re-execute the dispatcher. |

## Read models / false runtime by name

These surfaces may contain runtime terminology but are intentionally not execution authority:

- runtime readiness,
- runtime task preview,
- runtime dispatch readiness,
- worker claim readback,
- worker start readback,
- worker run readback,
- `GET` admission/readiness routes,
- Mission Brief.

These are not bugs. They are inspection, readiness, preview, or read-model surfaces.

## Declarative contract lanes

These lanes persist meaning, contracts, governance, or review state. They must not be treated as missing runtime because they do not execute.

| Lane | Classification | Meaning |
|---|---|---|
| Business Profile | Declarative profile-truth / suggestion contract with audit | Persists tenant-approved facts, suggestions, and decisions. Explicit business profile mutations append audit events. |
| Mission Brief | Read-model service-backed draft | Produces a draft brief from profile and mission context. It must not create missions, plans, task graphs, execution tasks, queue work, worker leases, evidence, outcome review, retrieval, runtime, or durable profile truth. |
| Capability registry | Declarative capability contract | Persists capability declarations. It must not bind runtime handlers automatically or execute runtime work. |
| Capability Adapter registry | Declarative adapter contract with compatibility validation | Persists adapter declarations and validates compatibility. It must not register executable runtime bindings or execute tools/providers directly. |
| Evidence API | Declarative evidence / provenance contract | Persists and updates evidence/provenance records. It must not score outcomes or dispatch runtime work. |
| Outcome Review | Declarative outcome-review contract | Persists review findings and decision metadata. It must not directly mutate runtime execution state. |
| Retrieval Contract | Declarative retrieval governance contract | Persists retrieval governance requests and statuses. It must not run embedding/vector retrieval implicitly or mutate runtime task execution state. |

## Declarative audit policy

Business Profile explicitly carries audit behavior.

Other declarative lanes, including Capability, Capability Adapter, Evidence API, Outcome Review, and Retrieval Contract, do not currently share the same explicit audit policy.

This should be treated as a design decision, not automatically as a bug.

Future work should choose one policy:

- keep current policy: Business Profile requires audit, other declarative lanes do not by default,
- broaden audit policy to all declarative mutation lanes,
- or define separate audit levels per lane.

Do not silently mix behavior.

## Evidence lanes

Evidence has two meanings and they must not be confused.

### Runtime evidence bridge

Active runtime path.

Tool actions return `ActionResult.evidence`. The evidence bridge converts completed `tool.invoke` output evidence into durable `EvidenceRecord` rows linked to task/lineage context.

The runtime evidence bridge is intentionally narrow. It should not be read as a universal bridge for every handler output.

### Evidence API

Declarative evidence/provenance persistence.

The API persists or updates evidence records but does not execute work, score outcomes, or dispatch runtime.

## Provider, credential, and egress lanes

### Active local/proof providers

Local providers are active runtime providers for current tool actions.

Examples include local calendar and local record providers.

### Credential / Secret Runtime Boundary

Credential authority is now an active runtime boundary, and one narrow read-only provider action is active. `ExecutionTask.metadata_json` may carry only a structured `credential_reference`; raw API keys, OAuth tokens, bearer tokens, webhook signing secrets, passwords, private keys, provider credentials, and similar secret fields are rejected before tool invocation proceeds.

The enforced path is:

`ExecutionTask.metadata_json.credential_reference` → `ToolRuntimeAuthority` → capability/ability promotion → `CredentialRuntimeAuthority` → runtime-only credential material on `ActionRuntimeContext.runtime_credentials` → `ActionRegistry` handler invocation → recursively redacted `ActionResult` / `EvidenceItem` output.

Runtime credential lookup fails closed when the reference is missing for an action that declares a `CredentialRequirement`, unknown, cross-tenant, disabled, revoked, deleted, provider/type incompatible, action-incompatible, or side-effect-class incompatible. Credentialed provider egress also fails closed when the requested URL host is not present in trusted credential destination metadata; invocation-provided `allowed_hosts` cannot expand that trust set. Credential existence is never permission to execute: capability/adapter/ability promotion and side-effect authorization still run first, and `ActionRegistry` remains the only execution registry. Runtime secret material is excluded from model serialization and is not copied into task metadata, task runtime context output, evidence payloads, action output, logs, or public denial strings. Evidence may record non-secret reference metadata such as `credential_id`, provider, and credential type.

This boundary uses `CredentialRuntimeAuthority` with a live SQLAlchemy-backed runtime credential repository in the `tool.invoke` worker path and a dedicated `AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY` Fernet protector for provider credential ciphertext; in-memory credential repositories are test-only. The only activated external provider path is `provider.external_read` for credentialed HTTPS GET/HEAD through credential-bound trusted destination validation and `NetworkEgressAuthority`; it does not claim production Vault/KMS integration, OAuth refresh, long-lived rotation, external CRM/GTM mutations, Google SDK activation, Kubernetes mTLS, cert-manager, or service mesh.

### Future-facing provider boundaries

`provider.external_read` is live as a generic read-only HTTPS GET/HEAD provider path. Google Calendar provider and legacy external credential resolver contracts are not live third-party provider clients yet.

- `GoogleCalendarProvider` is a future-facing provider boundary.
- It must not be described as live Google Calendar runtime.
- `ExternalCredentialReference` does not store plaintext secrets, decrypt credentials, call external services, or grant runtime authority.
- `UnresolvedCredentialResolver` fails closed and is not live secret resolution.

Calendar actions are real runtime actions, but currently backed by local/proof providers unless explicitly wired otherwise.

### Live external egress action surfaces

Future-facing provider boundaries are not the same as live external egress actions.

`provider.external_read`, `http.request`, and `webhook.dispatch` are live external egress action surfaces registered through the tool/action runtime. Only `provider.external_read` is the canonical read-only provider activation path; webhook remains send-only and HTTP remains a generic HTTP tool surface.

Important distinction:

- HTTP write methods and webhook dispatch are side-effecting egress surfaces.
- HTTP read methods such as `GET` and `HEAD` are `EXTERNAL_READ`.
- `EXTERNAL_READ` is not a mutating side effect, but it is an external runtime class and now requires tenant-visible capability/adapter promotion authority plus exact adapter classification before execution.
- HTTP read egress is therefore promotion-gated through `ToolRuntimeAuthority` while HTTP write/send egress additionally requires side-effect authorization and running task state.

`http.request` and webhook deliveries delegate outbound HTTP I/O to `NetworkEgressAuthority`; `http.request` enforces destination safety before live egress: HTTPS-only URLs, blocked localhost/.local/internal hostnames, blocked private/link-local/loopback/multicast/reserved/unspecified IP literals, blocked private DNS answers, DNS lookup failure as fail-closed, redirects disabled, and response body truncation to 4096 characters. For hostname destinations, the runtime pins one vetted public routable address from the validated DNS result and connects to that pinned address while preserving TLS SNI and HTTP Host semantics for the original hostname, so validation cannot approve one DNS answer and then connect through a later hostname re-resolution.

Payload-provided `allowed_hosts` remains an explicit request constraint, but it is not sufficient as sole destination authority: final destination safety is still enforced by runtime SSRF and DNS-rebinding hardening. Webhook dispatch keeps `EXTERNAL_SEND` authority and uses the same shared destination vetting, DNS pinning, original Host header, TLS SNI, fresh no-keepalive clients, forced per-request connection close, disabled redirects, and bounded response-body capture rather than inventing a webhook-specific egress policy.

## Mission queue authority

There are two API surfaces backed by one mission queue-admission authority. In this section, **runtime authority** means the service that enforces and mutates admission, **adapter** means an HTTP surface that authenticates and translates, and **metadata contract** means the receipt describing the completed decision. None of those terms describes a future boundary unless it is explicitly labelled as such.

### `POST /v1/missions/{mission_id}/queue` compatibility wrapper

Current meaning:

- The route requires `EXECUTION_QUEUE`, then delegates to the same `MissionRuntimeQueueAdmissionService.admit()` implementation as the canonical endpoint.
- It has no independent task selection, quota enforcement, `MissionExecutor`, or `ExecutionCoordinator` logic.
- It therefore queues only current tenant/mission-owned materialized planned tasks and persists the same `runtime_queue_admission` receipts, blockers, and authority metadata.
- It adapts the canonical result to the legacy `queued_task_ids`, `pending_review_task_ids`, and `denied_tasks` response only.
- It does not create execution tasks, create or mutate leases, dispatch workers, invoke `TaskDispatcher`, or execute handlers/adapters.

### `POST /v1/missions/{mission_id}/runtime-queue-admission` canonical API adapter to `MissionRuntimeQueueAdmissionService.admit`

Current meaning:

- `POST /v1/missions/{mission_id}/runtime-queue-admission` is the canonical staged runtime queue admission path.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` queues current materialized planned execution tasks.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` validates mission, tenant, and current materialization scope before admission.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` tracks blockers, already queued task IDs, admitted task IDs, pending-review outcomes, runtime-governor denials, and queue-task failures.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` calls `ExecutionCoordinator.queue_task()` for queue attempts.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` writes `runtime_queue_admission` metadata, receipts, blockers, admitted IDs, already queued IDs, and runtime authority details.
- `POST /v1/missions/{mission_id}/runtime-queue-admission` returns rich staged runtime admission information and remains the correct path for staged runtime correctness.

### Shared queue authority gate

This is not a queue-authority overlap: both routes invoke the same authoritative service, which reaches `ExecutionCoordinator.queue_task()`.

`ExecutionCoordinator.queue_task()` remains the shared queue authority gate. It owns RuntimeGovernor denial, PolicyGuardian pending-review routing, and DB-to-queue consistency for enqueue success or enqueue failure. Queue success is the only true queued result; governed non-queue outcomes are not broken runtime.

### Correct interpretation

The product decision is implemented: `MissionRuntimeQueueAdmissionService.admit()` owns mission lookup under a tenant-scoped row lock, current-materialization eligibility, one quota decision for newly queueable tasks, coordinator-backed queue transitions, already-queued idempotency, and the persisted/returned admission receipt. `POST /v1/missions/{mission_id}/runtime-queue-admission` is canonical only as an API entrypoint; `POST /v1/missions/{mission_id}/queue` is a response-compatibility adapter over the same authority.

## Known drift candidates and decisions needed

| Area | Current status | Needed decision |
|---|---|---|
| Mission queue API surfaces | Authority is consolidated: both routes call `MissionRuntimeQueueAdmissionService.admit()` and write the same admission metadata; `/queue` only adapts the response. | Preserve delegation and response-projection tests. |
| `POST /v1/missions/{mission_id}/queue` authority ledger | The route is classified as a compatibility wrapper over canonical runtime queue admission, not separate queue authority. | Preserve the wrapper boundary and legacy response shape. |
| Mission task graph cleanup | Graph persistence is declarative, but replacement cleanup may cancel superseded planned materialized `ExecutionTask` rows. | Keep graph persistence tests separate from cleanup mutation tests and ensure UPG/runtime-state invariants cover cleanup. |
| Mission route concentration | Runtime bridge mutation lanes now delegate to explicit services: `MissionRuntimeTaskMaterializationService`, `MissionRuntimeQueueAdmissionService`, `WorkerClaimAdmissionService`, `WorkerStartAdmissionService`, and `WorkerRunAdmissionService`; `backend/api/routes/mission.py` remains the route/auth/request/response wrapper. | Continue moving remaining response/read-model helpers out of the route when their contracts are separated. |
| Declarative mutation audit policy | Business Profile explicitly appends audit events; other declarative contract lanes generally do not. | Decide whether this is intentional or whether all declarative mutations require audit events. |
| Provider activation | One canonical read-only external provider path is active: `provider.external_read` performs credentialed HTTPS GET/HEAD only through ToolRuntimeAuthority, exact `external_read` adapter promotion, CredentialRuntimeAuthority, ActionRegistry, NetworkEgressAuthority, and redacted ActionResult/EvidenceItem output. Google Calendar, CRM/GTM mutations, OAuth refresh, writes/sends/publishes, and third-party SaaS SDK fleets remain inactive. | Build production secret backend/OAuth refresh/provider clients and mutation-specific safety proof before claiming broader live external provider activation. |
| Live HTTP/webhook egress | HTTP/webhook action egress is live under shared `NetworkEgressAuthority`. HTTP read egress is promotion-gated by tenant-visible capability/adapter authority and exact `external_read` adapter classification; HTTP write/send egress additionally requires side-effect authorization. HTTP and webhook network calls enforce SSRF protections, fail-closed DNS validation, and pinned vetted-address connection for hostname targets. | Preserve HTTP destination-safety, ability manifest, capability/adapter promotion, and side-effect authority tests when extending egress behavior. |

## Disproved assumptions

Do not repeat these assumptions in future audits or PRs.

| Bad assumption | Corrected fact |
|---|---|
| Runtime core is fake or missing. | Runtime core is real and includes coordinator, queue, worker runtime, worker loop, dispatcher, tool.invoke, action registry, evidence bridge, and recovery. |
| Every route using repositories directly is drift. | Many repository-using routes are declarative contract lanes by design. |
| Mutation without audit is automatically a bug. | Audit requirement depends on the authority contract. Business Profile explicitly requires audit; other lanes require a policy decision. |
| Runtime task materialization queues work. | It creates planned execution task rows only. |
| Mission task graph is always pure declarative metadata. | Graph persistence is declarative, but graph replacement cleanup can cancel superseded planned materialized `ExecutionTask` rows and should be covered as a governed cleanup mutation. |
| Worker run admission is read-only. | `POST /worker-run-admission` is true runtime execution through dispatcher. |
| Google Calendar is live runtime. | Google provider is a future-facing boundary and not live. |
| Google Calendar not live means no live external egress exists. | False. HTTP and webhook egress actions are live action/tool surfaces. |
| Business Profile routes are weakly tested or runtime-adjacent. | Business Profile is declarative/profile-truth with audit and tested tenant/permission/lifecycle behavior. |
| Pass 0 `auth_calls` count proves permission status. | The static map missed many `require_route_permission()` calls; direct route inspection is required. |

## Best path forward

### Phase 1 — Settle queue authority

Goal: remove queue authority ambiguity.

Actions:

1. Compare `POST /v1/missions/{mission_id}/queue` and `POST /v1/missions/{mission_id}/runtime-queue-admission`.
2. Declare `POST /v1/missions/{mission_id}/runtime-queue-admission` canonical for staged runtime queue admission.
3. Record that `POST /v1/missions/{mission_id}/queue` is retained only as a compatibility response wrapper.
4. Preserve authority-ledger coverage for `POST /v1/missions/{mission_id}/queue`.
5. Preserve regression tests proving both routes delegate to the same canonical implementation while their response envelopes remain compatible.

### Phase 2 — Lock current hardening gaps

Address the issues this audit exposed before broad refactors:

1. `POST /v1/missions/{mission_id}/queue` authority-ledger coverage,
2. `POST /v1/missions/{mission_id}/queue` vs `POST /v1/missions/{mission_id}/runtime-queue-admission` invariant tests,
3. queue admission policy/governance outcome tests,
4. queue/DB compensation failure-path tests,
5. `tool.invoke` side-effect authority regression tests,
6. runtime evidence bridge narrowness tests,
7. HTTP/webhook egress audit lane,
8. declarative audit policy decision,
9. mission task graph replacement cleanup invariants.

### Phase 3 — Extract mission runtime bridge services

Goal: reduce route-layer concentration.

Implemented bridge mutation services:

- `MissionRuntimeTaskMaterializationService`
- `MissionRuntimeQueueAdmissionService`
- `WorkerClaimAdmissionService`
- `WorkerStartAdmissionService`
- `WorkerRunAdmissionService`

Routes are permission/tenant/request/response wrappers around these services for the extracted mutation lanes.

### Phase 4 — Lock bridge invariant tests

Required invariants:

| Stage | Invariant |
|---|---|
| task graph | graph persistence must not queue, dispatch, or execute handlers; replacement cleanup may cancel superseded planned materialized tasks and needs its own governed mutation invariant |
| task materialization | creates only planned tasks |
| queue admission | queues only current materialized planned tasks through `ExecutionCoordinator` |
| claim admission | creates leases and moves queued to claimed only |
| start admission | activates lease and moves claimed to running only |
| run admission | claims queue payload before dispatcher execution |
| repeated run admission | does not re-execute completed task |

### Phase 5 — Provider activation plan

Do not wire Google Calendar directly into runtime yet.

Order:

1. add production credential storage/secret backend behind the existing runtime authority interface,
2. add OAuth refresh/rotation only with explicit tests and docs,
3. implement Google provider fail-closed,
4. add readback/idempotency tests,
5. swap calendar provider behind feature flag.

## Issue checklist exposed by this audit

Use this checklist to open or reconcile repo issues before implementation.

### Mission queue authority

- Preserve dedicated authority-ledger coverage for `POST /v1/missions/{mission_id}/queue`.
- Preserve tests proving both mission API entrypoints delegate to `MissionRuntimeQueueAdmissionService.admit()`.
- Preserve tests proving the compatibility route only projects the canonical result and cannot perform a second quota decision or queue transition.
- Preserve tests proving the service owns staged metadata, receipts, blockers, admitted IDs, already queued IDs, and runtime authority details.
- Preserve the product decision that `POST /v1/missions/{mission_id}/queue` is retained as a response compatibility adapter and is not a competing runtime engine.

### Runtime bridge invariants

- Prove task graph does not enqueue, dispatch, or execute handlers.
- Prove task materialization creates only `PLANNED` execution tasks.
- Prove claim admission only creates leases and moves queued tasks to claimed.
- Prove start admission only activates leases and moves claimed tasks to running.
- Prove run admission claims queue payload before dispatcher execution.
- Prove repeated run admission does not re-execute completed tasks.

### Queue failure-path safety

- Add or preserve tests for DB claim failure after queue claim.
- Add or preserve tests for queue release compensation.
- Add or preserve tests for terminal DB state committed before queue complete/fail.
- Add or preserve tests for retry behavior after partial queue/DB failure.

### Tool/action authority

- Preserve tests proving registered actions are not automatically executable.
- Preserve tests proving side-effecting actions require proper runtime state.
- Preserve tests proving side-effect authorization is required for write/send/publish actions.
- Preserve HTTP read-egress authority semantics (`GET`/`HEAD` as `EXTERNAL_READ`) while keeping destination-safety hardening fail-closed.

### Evidence

- Preserve tests proving runtime evidence bridge only converts completed `tool.invoke` output evidence.
- Add tests for non-tool handlers if future handlers are expected to emit durable evidence.
- Keep Evidence API distinct from runtime evidence bridge.

### Provider and egress

- Keep Google Calendar provider future-facing until credential resolver is implemented.
- Keep `UnresolvedCredentialResolver` fail-closed.
- Preserve shared network egress SSRF and DNS-rebinding hardening: fail-closed DNS validation, private/internal target rejection, pinned vetted-address connection, TLS SNI/Host preservation, redirects disabled, and bounded response truncation for HTTP/webhook surfaces.
- Treat HTTP read egress separately from HTTP write/send egress because `EXTERNAL_READ` is weaker-gated.

### Declarative lanes

- Decide whether Capability, Capability Adapter, Evidence API, Outcome Review, and Retrieval Contract should append audit events.
- Add no-runtime-call sentinels for declarative mutation lanes if missing.
- Keep Business Profile classified as declarative profile truth with audit.

### Route/service ownership

- Defer mission runtime bridge service extraction until queue authority is settled.
- When extracting, preserve staged responsibilities exactly.
- Do not move runtime authority into read-model or declarative lanes.

## Rule for future audits

Before calling something a bug, answer:

1. What lane is it in?
2. What authority does that lane own?
3. What authority is explicitly forbidden?
4. Does a test or authority ledger entry prove the intended behavior?
5. Is the concern a runtime bug, design decision, stale doc, future-facing contract, or separate hardening lane?
