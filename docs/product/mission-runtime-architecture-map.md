# Mission Runtime Architecture Map

Status: audit-grounded architecture reference  
Scope: mission runtime, queue authority, declarative contract lanes, future provider lanes  
Purpose: prevent future implementation work from mistaking intentional architecture boundaries for gaps.

## Executive summary

Ajenda has a real runtime core.

The system is not only declarative contracts, planning documents, or placeholder routes. The active runtime path is queue-backed and worker-dispatched:

Route / service admission
→ ExecutionCoordinator
→ QueueAdapter
→ WorkerRuntimeService
→ WorkerLoop
→ TaskDispatcher
→ task handler / tool.invoke
→ ActionRegistry / action handler
→ WorkerRuntimeService.complete or fail
→ lineage / evidence / audit
→ queue complete / fail / release

The system also has intentional non-runtime lanes. These include declarative contracts, read models, staged mission bridge routes, and future provider boundaries. These should not be treated as bugs merely because they do not execute work.

The main verified drift risk is mission queue authority overlap:

- `POST /v1/missions/{mission_id}/queue`
- `POST /v1/missions/{mission_id}/runtime-queue-admission`

Both reach `ExecutionCoordinator.queue_task()`, so this is not a queue-authority bypass. The risk is semantic divergence because the legacy `/queue` route queues planned mission tasks without writing staged runtime admission metadata, while `/runtime-queue-admission` is part of the staged runtime bridge and writes receipts, blockers, admitted task IDs, and runtime authority metadata.

## Classification vocabulary

Use these terms in future audits and PRs.

| Classification | Meaning |
|---|---|
| True runtime | Executes or directly advances executable work through queue, lease, dispatcher, handler, completion, evidence, or recovery. |
| Governed runtime mutation | Mutates runtime-adjacent state, but does not execute handlers. Example: creating planned execution tasks or activating worker leases. |
| Declarative contract lane | Persists contracts, metadata, review records, profiles, evidence records, or governance requests without executing runtime work. |
| Read model / false runtime by name | Uses runtime language but only reads or previews state. It must not mutate task, queue, lease, dispatcher, or handler state. |
| Future-facing provider boundary | Defines external provider or credential contracts but does not make live external calls yet. |
| Drift candidate | A path with overlapping meaning or unclear ownership that needs reconciliation before extension. |

## True runtime lane

The active worker runtime is real.

### Background worker runtime

Canonical lane:

ExecutionCoordinator
→ QueueAdapter
→ WorkerRuntimeService
→ WorkerLoop
→ TaskDispatcher
→ task handler / tool.invoke
→ WorkerRuntimeService.complete or fail
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

### tool.invoke runtime

`tool.invoke` is true runtime.

It validates:

- tenant scope,
- invocation shape,
- registered action existence,
- side-effect class,
- side-effect runtime state,
- capability / adapter authority.

It then invokes the default action registry and returns structured output including action name, provider, side-effect class, evidence, readback fields, changed records, summary, confidence, limitations, and runtime context.

## Mission runtime bridge

The mission runtime bridge is staged. Do not collapse these stages into a single vague “runtime” concept.

| Stage | Classification | Meaning |
|---|---|---|
| Mission task graph | Declarative contract | Persists task graph contract. It must not create execution tasks, enqueue, dispatch, or execute handlers. |
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

## Evidence lanes

Evidence has two meanings and they must not be confused.

### Runtime evidence bridge

Active runtime path.

Tool actions return `ActionResult.evidence`. The evidence bridge converts completed `tool.invoke` output evidence into durable `EvidenceRecord` rows linked to task/lineage context.

### Evidence API

Declarative evidence/provenance persistence.

The API persists or updates evidence records but does not execute work, score outcomes, or dispatch runtime.

## Provider and credential lanes

### Active local/proof providers

Local providers are active runtime providers for current tool actions.

Examples include local calendar and local record providers.

### Future-facing provider boundaries

Google Calendar provider and external credential resolution are not live runtime yet.

- `GoogleCalendarProvider` is a future-facing provider boundary.
- It must not be described as live Google Calendar runtime.
- `ExternalCredentialReference` does not store plaintext secrets, decrypt credentials, call external services, or grant runtime authority.
- `UnresolvedCredentialResolver` fails closed and is not live secret resolution.

Calendar actions are real runtime actions, but currently backed by local/proof providers unless explicitly wired otherwise.

### Live external egress action surfaces

Future-facing provider boundaries are not the same as live external egress actions.

The default `ActionRegistry` also registers actions such as `http.request` and `webhook.dispatch`. Those are live tool-action egress surfaces with explicit side-effect classes and runtime authority gates:

- `http.request` uses `httpx` and can perform `EXTERNAL_READ` or `EXTERNAL_WRITE` depending on method.
- `webhook.dispatch` uses `WebhookDispatchService` and is classified as `EXTERNAL_SEND`.

Therefore, “Google Calendar is not live” must not be read as “no live external egress exists.” Live HTTP/webhook egress belongs to the action/tool lane and must be audited through `ActionRegistry`, side-effect classes, capability/adapter authority, idempotency, evidence, and runtime execution tests.

## Mission queue authority

There are two active mission queue/admission paths.

### Legacy mission queue route

`POST /v1/missions/{mission_id}/queue`

Current meaning:

- queues all tenant-owned planned tasks for a mission,
- calls `MissionExecutor.queue_all_planned_tasks()`,
- reaches `ExecutionCoordinator.queue_task()`,
- returns a simple queue summary,
- does not write staged runtime queue admission metadata.

### Staged runtime queue admission route

`POST /v1/missions/{mission_id}/runtime-queue-admission`

Current meaning:

- queues current materialized planned tasks,
- validates mission/tenant/materialization scope,
- tracks already queued tasks and blockers,
- calls `ExecutionCoordinator.queue_task()`,
- writes runtime queue admission metadata and receipts,
- returns rich staged admission information.

### Correct interpretation

This is not a queue-authority bypass because both routes go through `ExecutionCoordinator.queue_task()`.

This is a semantic overlap / drift risk because the two paths have different meanings, metadata behavior, receipt behavior, blocker behavior, and downstream readiness implications.

### Canonical direction

`/runtime-queue-admission` should be treated as the canonical mission runtime queue admission path.

The legacy `/queue` route should not remain an independent queue implementation long term.

Preferred future role:

- compatibility wrapper,
- mission launch shortcut,
- or deprecated endpoint.

It should delegate to the canonical staged runtime queue admission service once that service exists.

## Known drift candidates and decisions needed

| Area | Current status | Needed decision |
|---|---|---|
| Two mission queue paths | Verified overlap. Both call `ExecutionCoordinator.queue_task()`, but only runtime queue admission writes staged metadata. | Decide whether `/queue` is deprecated, retained with documented difference, or rewritten as wrapper. |
| Mission route concentration | `backend/api/routes/mission.py` owns many bridge responsibilities. | Extract mission runtime bridge logic into explicit services. |
| Declarative mutation audit policy | Business Profile explicitly appends audit events; other declarative contract lanes generally do not. | Decide whether this is intentional or whether all declarative mutations require audit events. |
| Provider activation | Google Calendar and credential resolver are contract-only. | Build real credential resolver before live external provider. |

## Disproved assumptions

Do not repeat these assumptions in future audits or PRs.

| Bad assumption | Corrected fact |
|---|---|
| Runtime core is fake or missing. | Runtime core is real and includes coordinator, queue, worker runtime, worker loop, dispatcher, tool.invoke, action registry, evidence bridge, and recovery. |
| Every route using repositories directly is drift. | Many repository-using routes are declarative contract lanes by design. |
| Mutation without audit is automatically a bug. | Audit requirement depends on the authority contract. Business Profile explicitly requires audit; other lanes require a policy decision. |
| Runtime task materialization queues work. | It creates planned execution task rows only. |
| Worker run admission is read-only. | `POST /worker-run-admission` is true runtime execution through dispatcher. |
| Google Calendar is live runtime. | Google provider is a future-facing boundary and not live. |
| Business Profile routes are weakly tested or runtime-adjacent. | Business Profile is declarative/profile-truth with audit and tested tenant/permission/lifecycle behavior. |
| Pass 0 `auth_calls` count proves permission status. | The static map missed many `require_route_permission()` calls; direct route inspection is required. |

## Best path forward

### Phase 1 — Settle queue authority

Goal: remove queue authority ambiguity.

Actions:

1. Compare `/queue` and `/runtime-queue-admission`.
2. Declare `/runtime-queue-admission` canonical for mission runtime queue admission.
3. Decide whether `/queue` is deprecated, retained with documented semantics, or rewritten as wrapper.
4. Add authority-ledger coverage for `/queue` if retained.
5. Add regression tests proving legacy and canonical behavior do not diverge.

### Phase 2 — Extract mission runtime bridge services

Goal: reduce route-layer concentration.

Candidate services:

- `MissionRuntimeTaskMaterializationService`
- `MissionRuntimeQueueAdmissionService`
- `WorkerClaimAdmissionService`
- `WorkerStartAdmissionService`
- `WorkerRunAdmissionService`

Routes should become permission/tenant/request wrappers around these services.

### Phase 3 — Lock bridge invariant tests

Required invariants:

| Stage | Invariant |
|---|---|
| task graph | no task creation, no queue, no dispatch |
| task materialization | creates only planned tasks |
| queue admission | queues only current materialized planned tasks through `ExecutionCoordinator` |
| claim admission | creates leases and moves queued to claimed only |
| start admission | activates lease and moves claimed to running only |
| run admission | claims queue payload before dispatcher execution |
| repeated run admission | does not re-execute completed task |

### Phase 4 — Decide declarative audit policy

Choose one:

- Keep current policy: Business Profile requires audit; other declarative contract lanes do not by default.
- Broaden policy: capability, adapter, evidence, outcome-review, and retrieval mutations also append audit events.

Do not silently mix audit behavior.

### Phase 5 — Provider activation plan

Do not wire Google Calendar directly into runtime yet.

Order:

1. Implement concrete credential resolver.
2. Add encrypted credential storage contract.
3. Implement Google provider fail-closed.
4. Add readback/idempotency tests.
5. Swap calendar provider behind feature flag.

## Rule for future audits

Before calling something a bug, answer:

1. What lane is it in?
2. What authority does that lane own?
3. What authority is explicitly forbidden?
4. Does a test or authority ledger entry prove the intended behavior?
5. Is the concern a runtime bug, design decision, stale doc, or future-facing contract?


## Live file verification addendum — 2026-06-10

This addendum records a repo-visible verification pass against implementation, tests,
authority ledger entries, and validation scripts. The architecture map remains a
trustworthy build reference when the classifications and correction notes below are
kept with it.

### A. Files read

- Architecture document: `docs/product/mission-runtime-architecture-map.md`.
- Runtime: `backend/services/execution_coordinator.py`, `backend/queue/base.py`,
  `backend/queue/local_adapter.py`, `backend/queue/adapters/redis_adapter.py`,
  `backend/services/worker_runtime_service.py`, `backend/workers/worker_loop.py`,
  `backend/workers/task_dispatcher.py`.
- Mission bridge: `backend/api/routes/mission.py`,
  `backend/services/mission_executor.py`, `backend/runtime/transitions.py`,
  `backend/repositories/execution_task_repository.py`,
  `backend/repositories/worker_lease_repository.py`.
- Declarative lanes: `backend/api/routes/business_profile.py`,
  `backend/api/routes/mission_brief.py`, `backend/services/mission_brief.py`,
  `backend/api/routes/capability.py`, `backend/api/routes/capability_adapter.py`,
  `backend/api/routes/evidence.py`, `backend/api/routes/outcome_review.py`,
  `backend/api/routes/retrieval_contract.py`, and their matching domain and
  repository files where route code delegates persistence.
- Evidence: `backend/services/tools/evidence_bridge.py`,
  `backend/domain/evidence.py`, `backend/domain/lineage_record.py`,
  `backend/repositories/evidence_repository.py`,
  `backend/repositories/lineage_record_repository.py`.
- Providers/credentials: `backend/services/tools/calendar_actions.py`,
  `backend/services/tools/local_calendar.py`, `backend/services/tools/local_records.py`,
  `backend/services/tools/google_calendar_provider.py`,
  `backend/services/tools/external_credentials.py`,
  `backend/services/tools/credential_resolver.py`.
- Action/ability: `backend/workers/handlers/tool_invoke.py`,
  `backend/services/tools/action_registry.py`,
  `backend/services/tools/schemas.py`,
  `backend/services/tools/capability_validation.py`,
  `backend/services/abilities/catalog.py`, `backend/services/abilities/manifest.py`,
  `backend/services/abilities/role_contracts.py`.
- Tests: runtime integration tests under `tests/integration/runtime/`, queue
  contracts under `tests/contract/queue/`, mission queue/bridge tests under
  `tests/contract/api/test_mission_queue_contract.py` and
  `tests/integration/runtime/test_task_graph_runtime_admission_real.py`, worker
  admission tests under `tests/unit/api/test_worker_*_admission_contract.py`,
  tool/action/evidence/provider tests under `tests/unit/tools/` and
  `tests/unit/workers/`, and declarative lane tests under `tests/unit/api/` and
  `tests/contract/api/`.
- Authority ledger: `docs/contracts/authority-ledger.v1.yaml`.
- Schemas/migrations/validation: `backend/services/tools/schemas.py`, domain
  schema-version constants, `scripts/validation/contract_drift_check.py`,
  `scripts/validation/migration_seed_contract_check.py`, and
  `scripts/validation/ability_rollout_contract_check.py`.

### B. Architecture map verification table

| Document claim | Status | File evidence | Test evidence | Correction needed | Notes |
|---|---|---|---|---|---|
| True runtime lane exists: route/service admission -> `ExecutionCoordinator` -> queue -> worker runtime -> worker loop -> dispatcher -> handler -> completion/failure -> lineage/evidence/audit -> queue ack. | verified | `ExecutionCoordinator.queue_task()` tenant-loads tasks, gates governor/policy, transitions to queued, calls `QueueAdapter.enqueue_task()`, and appends audit/governance (`backend/services/execution_coordinator.py:55-188`). `WorkerLoop._claim_and_start_task()` uses `WorkerRuntimeService.claim_next_task()`, heartbeat, start, then `_run_claimed_task()` delegates to `TaskDispatcher.execute()` (`backend/workers/worker_loop.py:35-115`). `TaskDispatcher.execute()` selects handlers and always calls runtime complete/fail (`backend/workers/task_dispatcher.py:136-210`). `WorkerRuntimeService.complete()` appends lineage/evidence/audit and calls queue complete; `fail()` appends audit and calls queue fail (`backend/services/worker_runtime_service.py:127-236`). | `tests/integration/runtime/test_release_gating_runtime_real.py`, `tests/integration/runtime/test_worker_executes_echo_task_real.py`, `tests/contract/queue/test_queue_flow.py`. | none | What this proves: the lane exists and is queue/lease/dispatcher backed. What it does not prove: every mission route uses the lane; each route still needs authority classification. |
| `tool.invoke` is a real dispatcher/runtime path. | verified | `@register_handler("tool.invoke", output_reason="tool action completed")` registers the handler (`backend/workers/handlers/tool_invoke.py:15-16`). It validates tenant, invocation shape, side-effect state/authorization, capability/adapter authority, invokes `ActionRegistry`, and returns structured output/evidence/readback fields (`backend/workers/handlers/tool_invoke.py:17-86`). `ActionRegistry.invoke()` validates input, executes handler, validates `ActionResult`, and JSON-serializes output (`backend/services/tools/action_registry.py:34-84`). | `tests/unit/workers/test_tool_invoke_handler.py`, `tests/unit/workers/test_task_dispatcher_registry.py`, `tests/integration/runtime/test_worker_executes_tool_invoke_task_real.py`. | none | What this proves: `tool.invoke` executes in dispatcher runtime. What it does not prove: declarative capability/adapter declarations execute anything by themselves. |
| Mission task graph is declarative and must not create execution tasks, queue, dispatch, or execute. | verified | Mission task graph routes persist normalized graph metadata under mission metadata; runtime task creation is only in `materialize_mission_runtime_tasks()` (`backend/api/routes/mission.py:1246-1322`, `backend/api/routes/mission.py:3169-3260`). | `tests/unit/api/test_mission_intake_route.py::test_mission_task_graph_post_creates_graph_without_queueing`, `::test_graph_materialization_persists_metadata_without_queueing_or_runtime_calls`. | none | What this proves: graph persistence is separated from runtime task rows. What it does not prove: future graph endpoints cannot drift without tests. |
| Runtime task materialization creates `PLANNED` `ExecutionTask` rows only and does not queue or dispatch. | verified | `materialize_mission_runtime_tasks()` requires `RUNTIME_OPERATE`, builds preview payloads, inserts `ExecutionTask(status=PLANNED)`, writes materialization metadata, and has no queue/dispatcher calls (`backend/api/routes/mission.py:3169-3260`). | `tests/unit/api/test_mission_intake_route.py::test_graph_materialization_persists_metadata_without_queueing_or_runtime_calls`; authority ledger `runtime_task_materialization_mutation_contract` (`docs/contracts/authority-ledger.v1.yaml:235-254`). | none | What this proves: creation state is planned-only. What it does not prove: all possible materialized metadata is schema-hardened. |
| Runtime queue admission queues current materialized planned tasks through `ExecutionCoordinator` and writes admission metadata. | verified | `runtime_queue_admission()` checks permission, validates mission/materialization scope, queues planned materialized tasks via `ExecutionCoordinator.queue_task()`, and writes `runtime_queue_admission` metadata (`backend/api/routes/mission.py:5762-5886`). | `tests/integration/runtime/test_task_graph_runtime_admission_real.py::test_runtime_queue_admission_route_admits_current_materialized_tasks_real`; authority ledger `runtime_queue_admission_contract` (`docs/contracts/authority-ledger.v1.yaml:255-276`). | none | What this proves: canonical staged queue admission goes through coordinator. What it does not prove: `/queue` has equivalent staged metadata semantics. |
| Worker claim admission creates leases and moves queued -> claimed only. | verified | `_build_worker_claim_admission()` validates preview/task/tenant/lease state, transitions queued tasks to claimed, adds `WorkerLease(status=CLAIMED)`, writes `worker_lease_id`, and stores claim receipts (`backend/api/routes/mission.py:4156-4415`). | `tests/unit/api/test_worker_claim_admission_contract.py`; authority ledger `worker_claim_admission_mutation_contract` (`docs/contracts/authority-ledger.v1.yaml:298-318`). | none | What this proves: claim admission mutates task/lease state but does not dispatch. What it does not prove: queue payload is claimed here; staged run admission claims queue payload later. |
| Worker start admission activates leases and moves claimed -> running only. | verified | `_build_worker_start_admission()` validates claim metadata, task/tenant/lease/holder state, activates claimed leases, transitions task to running, and writes start receipts (`backend/api/routes/mission.py:4645-5017`). The POST route documents no dispatcher execution (`backend/api/routes/mission.py:5020-5028`). | `tests/unit/api/test_worker_start_admission_contract.py`; authority ledger `worker_start_admission_mutation_contract` (`docs/contracts/authority-ledger.v1.yaml:340-359`). | none | What this proves: start admission is governed mutation. What it does not prove: handler execution; that belongs to run admission. |
| Worker run admission is true runtime execution through dispatcher and is idempotent after terminal state. | verified | `_build_worker_run_admission()` validates start/current lease state, calls `queue.claim_existing_task()` before `TaskDispatcher.execute()`, records queue claims/run receipts, and returns already-completed/already-failed receipts instead of re-executing terminal tasks (`backend/api/routes/mission.py:5320-5725`). POST route requires runtime permission (`backend/api/routes/mission.py:5728-5738`). | `tests/unit/api/test_worker_run_admission_contract.py`; authority ledger `worker_run_admission_mutation_contract` (`docs/contracts/authority-ledger.v1.yaml:383-403`). | none | What this proves: POST run admission can execute handlers. What it does not prove: the GET readback executes anything; it does not. |
| Readiness, previews, GET admission/readiness routes, worker readbacks, and Mission Brief are read-model or preview surfaces. | verified | Runtime readiness/preview GET routes return built projections without queue/dispatcher calls (`backend/api/routes/mission.py:3025-3081`). GET materialization/readback routes read metadata only (`backend/api/routes/mission.py:3152-3166`, `backend/api/routes/mission.py:5741-5759`, `backend/api/routes/mission.py:5889-5902`). Mission Brief authority ledger forbids missions, task graphs, execution tasks, queues, leases, evidence, outcome review, retrieval, runtime, and profile truth mutations (`docs/contracts/authority-ledger.v1.yaml:443-467`). | `tests/unit/api/test_runtime_dispatch_readiness_contract.py`, `tests/unit/api/test_worker_dispatch_eligibility_contract.py`, `tests/unit/api/test_mission_brief_route.py`, `tests/contract/api/test_mission_brief_routes.py`. | none | What this proves: these named runtime surfaces are not runtime authority. What it does not prove: all future GET routes stay read-only without ledger/tests. |
| Declarative lanes persist contracts/state rather than execute runtime: Business Profile, Mission Brief, Capability, Adapter, Evidence API, Outcome Review, Retrieval Contract. | verified | Authority ledger classifies these lanes as declarative/read-model and forbids runtime execution: capability (`docs/contracts/authority-ledger.v1.yaml:405-423`), adapter (`docs/contracts/authority-ledger.v1.yaml:424-442`), mission brief (`docs/contracts/authority-ledger.v1.yaml:443-467`), business profile (`docs/contracts/authority-ledger.v1.yaml:468-498`), evidence (`docs/contracts/authority-ledger.v1.yaml:499-517`), outcome review (`docs/contracts/authority-ledger.v1.yaml:518-535`), retrieval (`docs/contracts/authority-ledger.v1.yaml:537-555`). | Matching tests listed in those ledger entries. | none | What this proves: current route/service contracts are non-runtime. What it does not prove: each mutation's audit policy is uniform; that remains a policy decision. |
| Evidence lanes are distinct: runtime evidence bridge vs Evidence API. | verified | Runtime bridge builds durable `EvidenceRecord` rows only from completed `tool.invoke` outputs and validates evidence tenant/task/mission scope (`backend/services/tools/evidence_bridge.py:25-158`). `WorkerRuntimeService.complete()` appends lineage then bridges evidence (`backend/services/worker_runtime_service.py:127-188`). Evidence API is ledgered as declarative persistence and forbids outcome scoring/runtime dispatch (`docs/contracts/authority-ledger.v1.yaml:499-517`). | `tests/unit/tools/test_evidence_bridge.py`, `tests/unit/api/test_evidence_route.py`, `tests/unit/repositories/test_evidence_repository.py`, `tests/integration/runtime/test_worker_executes_tool_invoke_task_real.py`. | none | What this proves: runtime evidence is bridged from action output; Evidence API is direct evidence/provenance persistence. What it does not prove: Evidence API mutations append audit events. |
| Local providers are active proof providers; Google Calendar and credential resolution are future-facing/fail-closed. | verified | Calendar actions call `LocalCalendarProvider` and register `provider="local_calendar"` (`backend/services/tools/calendar_actions.py:16-104`). Local providers are tenant-scoped deterministic proof providers (`backend/services/tools/local_calendar.py:11-54`, `backend/services/tools/local_records.py:29-112`). `GoogleCalendarProvider` imports no SDK and raises `NotImplementedError` for read/create after tenant validation (`backend/services/tools/google_calendar_provider.py:1-69`). `ExternalCredentialReference` forbids plaintext secrets (`backend/services/tools/external_credentials.py:1-76`). `UnresolvedCredentialResolver.resolve()` always raises `NotImplementedError` (`backend/services/tools/credential_resolver.py:1-45`). | `tests/unit/tools/test_calendar_provider_contract.py`, `tests/unit/tools/test_google_calendar_provider_contract.py`, `tests/unit/tools/test_external_credentials.py`, `tests/unit/tools/test_credential_resolver_contract.py`, `tests/unit/tools/test_local_records.py`. | none | What this proves: no live Google Calendar provider is wired in these files. What it does not prove: absence of all external calls globally; separate network-surface audits are still needed. |
| Two mission queue/admission paths overlap but both reach `ExecutionCoordinator.queue_task()`. | verified drift risk | `/queue` counts tenant-owned planned tasks, enforces quota, then calls `MissionExecutor.queue_all_planned_tasks()` which calls `ExecutionCoordinator.queue_task()` (`backend/api/routes/mission.py:5905-5963`, `backend/services/mission_executor.py:27-62`). `/runtime-queue-admission` calls `ExecutionCoordinator.queue_task()` and writes rich staged metadata (`backend/api/routes/mission.py:5762-5886`). | `/queue` contract tests prove quota/filtering/simple summary (`tests/contract/api/test_mission_queue_contract.py:58-210`). Runtime admission integration test proves staged metadata/authority flags (`tests/integration/runtime/test_task_graph_runtime_admission_real.py:223-262`). | none in current map; keep drift risk explicit | What this proves: not a queue-authority bypass. What it does not prove: these endpoints cannot semantically diverge; they already have different metadata contracts. |
| Known drift: mission route concentration. | verified drift risk | `backend/api/routes/mission.py` contains many schemas/helpers/routes for graph, readiness, materialization, queue admission, claim/start/run admission, and `/queue`; endpoint lines alone span at least `3025-5963`. | Tests are broad but route-centric across many files. | no immediate refactor required | The drift is ownership/concentration risk, not a proven runtime bypass. |
| Known drift: declarative mutation audit policy inconsistency. | design decision required | Business Profile ledger explicitly allows audit events (`docs/contracts/authority-ledger.v1.yaml:468-498`). Capability, adapter, evidence, outcome, and retrieval ledger entries do not require audit events (`docs/contracts/authority-ledger.v1.yaml:405-555`). | Declarative tests focus on persistence/tenant boundaries. | policy decision needed before broad changes | Current map should keep this as a decision, not a bug. |
| Known drift: provider activation gap. | verified drift risk | Runtime registry registers local calendar actions only (`backend/services/tools/action_registry.py:101-120`, `backend/services/tools/calendar_actions.py:91-104`); Google provider and credential resolver are contract-only/fail-closed (`backend/services/tools/google_calendar_provider.py:1-69`, `backend/services/tools/credential_resolver.py:39-45`). | Provider contract tests listed above. | none | This matters before any live external provider wiring. |
| Disproved assumptions table. | verified | Runtime core, planned-only materialization, true run admission, non-live Google provider, Business Profile declarative/audit, and unreliable static auth counts are all backed by the file evidence above and direct route permission calls such as `require_route_permission()` on mutation routes (`backend/api/routes/mission.py:3177`, `backend/api/routes/mission.py:5737`, `backend/api/routes/mission.py:5923`). | Tests listed above. | none | The table is trustworthy, with the caveat that "mutation without audit" remains policy-specific rather than globally allowed. |

### C. Corrected architecture map

Only repo-proven statements should be used as build reference:

1. The runtime core is real and queue/lease/dispatcher backed. Work enters queue
   authority through `ExecutionCoordinator.queue_task()`, worker ownership is
   represented by queue claims plus `WorkerLease` rows, handler execution is
   performed by `TaskDispatcher`, and terminal state is handled through
   `WorkerRuntimeService.complete()` or `WorkerRuntimeService.fail()`.
2. `tool.invoke` is a registered runtime handler. It validates tenant scope,
   invocation schema, side-effect state, side-effect authorization, and
   capability/adapter authority before invoking the default `ActionRegistry`.
3. Mission bridge stages are separate contracts: task graph is declarative;
   task materialization creates only planned `ExecutionTask` rows; runtime queue
   admission queues current planned materialized tasks and writes staged metadata;
   worker claim/start admissions are governed task/lease mutations; worker run
   admission claims the queue payload and executes the dispatcher.
4. Runtime readiness, previews, GET readbacks, and Mission Brief are read models
   or previews, not runtime execution authority.
5. Business Profile, Capability registry, Capability Adapter registry, Evidence
   API, Outcome Review, and Retrieval Contract are declarative contract lanes in
   current code and ledger entries. Business Profile explicitly requires audit;
   extending audit to the other declarative lanes is a design decision.
6. Runtime evidence bridge and Evidence API are distinct. The bridge persists
   evidence from completed `tool.invoke` output through lineage context; the API
   persists evidence/provenance records directly and must not dispatch runtime.
7. Calendar actions are live runtime actions backed by local/proof providers.
   Google Calendar and credential resolution are future-facing, fail-closed
   contracts until a real credential resolver and external client are wired.
8. Live HTTP and webhook egress actions exist independently of the Google
   Calendar provider boundary. They are registered in the default `ActionRegistry`
   and must be governed as `http.request` (`EXTERNAL_READ`/`EXTERNAL_WRITE`) and
   `webhook.dispatch` (`EXTERNAL_SEND`) runtime tool actions.
9. `/queue` and `/runtime-queue-admission` both reach `ExecutionCoordinator`, so
   the overlap is not a queue-authority bypass. It is a verified drift risk
   because `/queue` returns simple summary and does not write staged runtime queue
   admission metadata, while `/runtime-queue-admission` writes staged receipts,
   blockers, authority flags, and admission metadata.

### D. Omitted truths found during verification

| Omitted truth | File evidence | Why it matters | Suggested doc addition |
|---|---|---|---|
| `ExecutionCoordinator.queue_task()` is also a policy/compliance gate, not merely an enqueue wrapper. | Governor and policy checks can deny, move to pending review, append governance/audit, or enqueue (`backend/services/execution_coordinator.py:65-188`). | Queue admission semantics include compliance review and denial states. | Add: "Queue admission includes runtime governor and PolicyGuardian checks; admitted, denied, and pending-review outcomes are all first-class." |
| Queue adapters are fail-closed around ownership and recovery. | `QueueAdapter` contract requires explicit claim/complete/fail/release/recovery/dead-letter operations (`backend/queue/base.py:45-113`); local adapter rejects wrong owners and avoids synthesizing missing retry work (`backend/queue/local_adapter.py:51-145`). | Reinforces lease/queue authority invariants and recovery safety. | Add: "Queue payload recovery must not synthesize work from DB state; adapters must fail closed when queue evidence is missing." |
| Runtime completion currently commits DB state before queue ack. | `WorkerRuntimeService.complete()` flushes/commits task/lineage/evidence/audit before `queue.complete_task()` and raises on failed queue cleanup (`backend/services/worker_runtime_service.py:127-188`). | This is an important operational split-brain visibility point. | Add as a known runtime compensation/observability invariant, not as a bug. |
| Staged worker claim admission creates DB leases but does not claim queue payload; staged worker run admission claims the queue payload immediately before dispatcher execution. | Claim admission writes `WorkerLease` and task state (`backend/api/routes/mission.py:4302-4351`); run admission calls `queue.claim_existing_task()` before dispatcher execution (`backend/api/routes/mission.py:5582-5614`). | Prevents future agents from assuming claim admission alone owns queue processing payload. | Add: "In the staged bridge, DB claim and queue processing claim are deliberately separated until run admission." |
| Local calendar writes are runtime side effects but local/proof-scoped, not external Google writes. | `calendar.create_event` returns `INTERNAL_WRITE` and provider `local_calendar` (`backend/services/tools/calendar_actions.py:56-104`). | Avoids both overstating Google activation and understating local write side effects. | Add: "Calendar create is side-effecting runtime, but current side effect is local proof-provider state." |

### E. Hardening candidates

| Candidate | Classification | Evidence | Suggested smallest hardening |
|---|---|---|---|
| `/queue` authority-ledger coverage. | verified drift risk | Ledger covers `/runtime-queue-admission` but no distinct `/v1/missions/{mission_id}/queue` entry was found by direct search; `/queue` is runtime queue authority through `MissionExecutor` and `ExecutionCoordinator` (`backend/api/routes/mission.py:5905-5963`, `backend/services/mission_executor.py:35-62`). | Add a dedicated authority-ledger entry for legacy mission queue or explicitly include it as compatibility route under runtime queue admission. |
| `/queue` vs `/runtime-queue-admission` non-divergence tests. | verified drift risk | Existing tests prove each endpoint separately (`tests/contract/api/test_mission_queue_contract.py:58-210`, `tests/integration/runtime/test_task_graph_runtime_admission_real.py:223-262`). | Add a contract test that documents intentional differences and fails if `/queue` starts writing staged metadata or `/runtime-queue-admission` stops writing it. |
| Mission runtime bridge response schemas. | partially verified | Routes return Pydantic response models, but metadata is still JSON dict-heavy in route helpers. | Add schema tests for queue admission metadata, claim/start/run receipts, and runtime authority flags. |
| Declarative lane runtime-surface negative tests. | partially verified | Ledger forbids runtime mutation for declarative lanes; tests exist by lane, but not all assert absence of `ExecutionCoordinator`, `TaskDispatcher`, or `WorkerRuntimeService` calls. | Add focused negative tests for capability/adapter/evidence/outcome/retrieval routes patching runtime surfaces as not-called. |
| Provider/credential contract validation. | verified drift risk | Google and resolver fail closed; local provider is active. | Add a validation script or test sentinel that default action registry calendar provider remains `local_calendar` until a feature-flagged credential resolver exists. |
| Evidence/provenance schema parity. | partially verified | Runtime bridge validates `EvidenceItem` and writes `EvidenceRecord`; Evidence API persists evidence records separately. | Add contract tests that compare runtime bridge persisted evidence shape with Evidence API accepted schema for shared fields and provenance expectations. |

### F. Missing or weak invariant tests

- Task graph no-runtime invariant is mostly covered, but should explicitly patch
  `ExecutionCoordinator`, `QueueAdapter`, `TaskDispatcher`, and
  `WorkerRuntimeService` together for the task graph POST route.
- Runtime task materialization planned-only behavior is covered; strengthen by
  asserting no queue adapter calls and no dispatcher calls for every materialized
  task count path, including idempotent existing-materialization return.
- Queue admission current-materialization-only behavior is covered for the happy
  integration path; add stale-materialization and mixed planned/queued/completed
  comparisons against `/queue`.
- `/queue` and `/runtime-queue-admission` need an explicit semantic divergence
  regression test: both must call `ExecutionCoordinator.queue_task()`, but only
  runtime queue admission should write `runtime_queue_admission` metadata.
- Claim admission should keep asserting queued -> claimed only and lease creation;
  add a negative assertion that it does not call `queue.claim_existing_task()`.
- Start admission should keep asserting claimed -> running only; add a negative
  assertion that it does not construct or call `TaskDispatcher`.
- Run admission should keep asserting queue payload claim before dispatcher; add a
  test that a missing queue payload blocks without dispatcher execution even when
  DB task/lease state looks valid.
- Repeated run admission terminal idempotency is covered in route tests; keep it
  as a release gate because it protects against duplicated external mutations.
- Declarative lanes should gain one shared helper test that confirms no direct
  runtime-surface calls for capability, adapter, evidence, outcome, and retrieval
  mutations.
- Provider contracts should add a default-registry sentinel proving no
  `GoogleCalendarProvider` is used by active calendar actions until credential
  resolution is implemented and feature-gated.

### G. Smallest safe next PR recommendation

The smallest safe next PR is authority-ledger hardening for the legacy mission
queue route:

1. Add a dedicated `mission_queue_legacy_contract` ledger entry for
   `POST /v1/missions/{mission_id}/queue`, classified as
   `runtime_authoritative` / `tenant_scoped_queue_admission_mutation`.
2. State that it is a compatibility/simple-summary path that queues tenant-owned
   planned tasks through `MissionExecutor.queue_all_planned_tasks()` and
   `ExecutionCoordinator.queue_task()`.
3. Forbid staged queue admission metadata writes, task creation, dispatcher
   calls, worker lease mutation, and queue-authority bypass.
4. Add or update a narrow ledger validation/contract test proving `/queue` is
   ledger-covered and remains distinct from `/runtime-queue-admission`.

This is smaller and safer than extracting mission services or changing endpoint
semantics. It turns the main verified drift risk into an explicit contract before
future refactors.

### Final honesty note

- This pass verified repo-visible implementation, tests, authority ledger, and
  validation scripts only. It did not inspect external audit zip artifacts or
  production runtime telemetry.
- The map is trustworthy as a build reference for current architecture boundaries,
  provided future work treats the queue overlap, route concentration, declarative
  audit policy, provider activation, and live HTTP/webhook egress as explicit
  design/hardening items rather than assumptions.
- The statement "no hidden live external provider call exists" should not be used
  globally. The verified claim is narrower: Google Calendar and credential-resolved
  external providers are not live, while `http.request` and `webhook.dispatch` are
  live external egress action surfaces that require their own audits.
