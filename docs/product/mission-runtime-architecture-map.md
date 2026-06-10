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

