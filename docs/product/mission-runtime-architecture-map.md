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
| Future-facing provider boundary | Defines external provider or credential contracts but does not make live provider calls yet. |
| Live egress action surface | A runtime tool/action path that can make outbound network or delivery calls, such as HTTP or webhook actions. |
| Drift candidate | A path with overlapping meaning or unclear ownership that needs reconciliation before extension. |

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
- capability / adapter authority where applicable.

A registered `ActionDefinition` does not mean an action is freely executable. Registry presence is not execution authority.

For side-effecting actions, `tool.invoke` must preserve the rule that side effects require the proper runtime state and explicit authority.

## Mission runtime bridge

The mission runtime bridge is staged. Do not collapse these stages into a single vague “runtime” concept.

| Stage | Classification | Meaning |
|---|---|---|
| Mission task graph | Declarative contract | Persists task graph contract. It must not enqueue, dispatch, or execute handlers. Replacement may supersede graph metadata and cancel superseded planned materialized tasks, so this stage is not merely passive text storage. |
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

### Future-facing provider boundaries

Google Calendar provider and external credential resolution are not live runtime providers yet.

- `GoogleCalendarProvider` is a future-facing provider boundary.
- It must not be described as live Google Calendar runtime.
- `ExternalCredentialReference` does not store plaintext secrets, decrypt credentials, call external services, or grant runtime authority.
- `UnresolvedCredentialResolver` fails closed and is not live secret resolution.

Calendar actions are real runtime actions, but currently backed by local/proof providers unless explicitly wired otherwise.

### Live external egress action surfaces

Future-facing provider boundaries are not the same as live external egress actions.

`http.request` and `webhook.dispatch` are live external egress action surfaces registered through the tool/action runtime.

Important distinction:

- HTTP write methods and webhook dispatch are side-effecting egress surfaces.
- HTTP read methods such as `GET` and `HEAD` are `EXTERNAL_READ`.
- `EXTERNAL_READ` is not currently treated as side-effecting in the same way as write/send egress.
- Therefore HTTP read egress has weaker authority gating than write/send egress unless a capability/adapter reference or future policy requires more.

This document records the architecture truth only. It does not attempt to harden HTTP/network behavior.

HTTP/network egress hardening is a separate future work lane and should be handled in the dedicated HTTP/network PR/issues rather than hidden inside this architecture-map PR.

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
| Legacy `/queue` authority ledger | `/queue` is live and tested, and it reaches `ExecutionCoordinator.queue_task()` through `MissionExecutor.queue_all_planned_tasks()`. It does not currently have the same dedicated authority-ledger coverage as `/runtime-queue-admission`. | Add explicit authority-ledger coverage for legacy `/queue`, or formally wrap/deprecate it. |
| Mission route concentration | `backend/api/routes/mission.py` owns many bridge responsibilities. | Extract mission runtime bridge logic into explicit services after queue authority is settled. |
| Declarative mutation audit policy | Business Profile explicitly appends audit events; other declarative contract lanes generally do not. | Decide whether this is intentional or whether all declarative mutations require audit events. |
| Provider activation | Google Calendar and credential resolver are contract-only. | Build real credential resolver before live external provider activation. |
| Live HTTP/webhook egress | HTTP/webhook action egress is live, but HTTP read egress is weaker-gated than write/send egress. | Track and harden in the dedicated HTTP/network issue lane. |

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
| Google Calendar not live means no live external egress exists. | False. HTTP and webhook egress actions are live action/tool surfaces. |
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

### Phase 2 — Lock current hardening gaps

Address the issues this audit exposed before broad refactors:

1. legacy `/queue` authority-ledger coverage,
2. `/queue` vs `/runtime-queue-admission` invariant tests,
3. queue admission policy/governance outcome tests,
4. queue/DB compensation failure-path tests,
5. `tool.invoke` side-effect authority regression tests,
6. runtime evidence bridge narrowness tests,
7. HTTP/webhook egress audit lane,
8. declarative audit policy decision.

### Phase 3 — Extract mission runtime bridge services

Goal: reduce route-layer concentration.

Candidate services:

- `MissionRuntimeTaskMaterializationService`
- `MissionRuntimeQueueAdmissionService`
- `WorkerClaimAdmissionService`
- `WorkerStartAdmissionService`
- `WorkerRunAdmissionService`

Routes should become permission/tenant/request wrappers around these services.

### Phase 4 — Lock bridge invariant tests

Required invariants:

| Stage | Invariant |
|---|---|
| task graph | no queue, no dispatch, no handler execution |
| task materialization | creates only planned tasks |
| queue admission | queues only current materialized planned tasks through `ExecutionCoordinator` |
| claim admission | creates leases and moves queued to claimed only |
| start admission | activates lease and moves claimed to running only |
| run admission | claims queue payload before dispatcher execution |
| repeated run admission | does not re-execute completed task |

### Phase 5 — Provider activation plan

Do not wire Google Calendar directly into runtime yet.

Order:

1. implement concrete credential resolver,
2. add encrypted credential storage contract,
3. implement Google provider fail-closed,
4. add readback/idempotency tests,
5. swap calendar provider behind feature flag.

## Issue checklist exposed by this audit

Use this checklist to open or reconcile repo issues before implementation.

### Mission queue authority

- Add dedicated authority-ledger coverage for `POST /v1/missions/{mission_id}/queue`.
- Add tests proving `/queue` reaches `ExecutionCoordinator.queue_task()`.
- Add tests proving `/queue` does not write staged runtime queue admission metadata unless intentionally wrapped.
- Add tests proving `/runtime-queue-admission` owns staged metadata/receipts/blockers.
- Decide whether `/queue` is retained, deprecated, or rewritten as a wrapper.

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
- Clarify or harden HTTP read-egress authority if existing HTTP/network issues are not sufficient.

### Evidence

- Preserve tests proving runtime evidence bridge only converts completed `tool.invoke` output evidence.
- Add tests for non-tool handlers if future handlers are expected to emit durable evidence.
- Keep Evidence API distinct from runtime evidence bridge.

### Provider and egress

- Keep Google Calendar provider future-facing until credential resolver is implemented.
- Keep `UnresolvedCredentialResolver` fail-closed.
- Track HTTP/webhook egress hardening in the dedicated HTTP/network issue lane.
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
