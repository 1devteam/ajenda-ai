# Capability Action Runtime Layer Evaluation and Completion Plan

**Status:** Lab-branch evaluation plan  
**Date:** 2026-06-04  
**Owner:** AJENDA-AI runtime/product architecture  
**Scope:** Additive completion plan for turning capability/adapter/task metadata into executable modular actions through the existing runtime/worker/dispatcher path.

## Executive conclusion

The repository already has a real queue-authoritative execution spine: mission graph readiness, task preview, runtime task materialization, runtime queue admission, worker claim/start/run admission, `WorkerLoop`, `TaskDispatcher`, handler registration, worker leases, task state transitions, audit records, and task-output lineage persistence. The current implementation does **not** have a generic capability action runtime layer for `tool.invoke`, `record.search`, `http.request`, `webhook.dispatch`, CRM/GTM action packs, or provider-backed action execution. Existing capability and adapter records are explicitly declarative and must not be treated as execution proof.

The correct completion path is additive: register one generic `tool.invoke` handler through the current dispatcher registry, add a separate action registry and tool/action modules, validate task metadata against existing capability/adapter declarations, return dispatcher-valid structured results, and let `TaskDispatcher` and `WorkerRuntimeService.complete/fail` remain the authority for completion, failure, leases, audit, queue mutation, and lineage output.

## Evidence-based findings

### Finding: Runtime execution spine

**Status:** Implemented

**Evidence:**

- `backend/workers/task_dispatcher.py` defines `register_handler`, `_HANDLER_REGISTRY`, task-type extraction from `ExecutionTask.metadata_json["task_type"]`, handler result validation, heartbeat maintenance, completion, and failure paths.
- `backend/workers/worker_loop.py` claims tasks, starts execution, and delegates execution to `TaskDispatcher`.
- `backend/services/worker_runtime_service.py` owns queue claim, lease creation, heartbeat, start, complete, fail, lease release, audit events, queue completion/failure, and optional task-output lineage persistence.
- `tests/unit/workers/test_task_dispatcher_registry.py`, `tests/unit/workers/test_task_dispatcher_runtime_contract.py`, `tests/unit/workers/test_worker_loop_contracts.py`, `tests/integration/runtime/test_worker_executes_echo_task_real.py`, and `tests/integration/runtime/test_dispatcher_failure_state_real.py` prove handler registration, dispatcher contracts, worker-loop delegation, successful echo execution, and failure-state behavior.

**Reasoning:**

The runtime spine is not a placeholder. It dispatches by metadata task type, executes registered handlers, validates handler output, heartbeats during execution, and completes or fails through `WorkerRuntimeService`. The task action layer must plug into this handler registry rather than replacing worker or queue authority.

What this does **not** prove: it does not prove any generic action registry, provider abstraction, or capability-driven action execution exists. Current built-in handlers are `default`, `force_fail`, and `echo` only.

**Risk:**

- **Duplicate architecture risk:** high if a new executor bypasses `TaskDispatcher`.
- **Authority drift risk:** high if actions mutate task state directly instead of returning handler output.
- **Schema drift risk:** medium if action output shape diverges from dispatcher validation.
- **Tenant leak risk:** medium if action providers do not receive tenant-scoped context.
- **Runtime shortcut risk:** high if actions bypass queue/lease completion semantics.

### Finding: Handler registry extension point

**Status:** Implemented

**Evidence:**

- `backend/workers/task_dispatcher.py` exposes `register_handler(task_type, output_reason=None)` and stores handlers in `_HANDLER_REGISTRY`.
- `TaskDispatcher.execute` selects `_HANDLER_REGISTRY[task_type]` or the `default` handler and fails the task if no handler exists.
- The dispatcher only persists handler output to lineage when the task type was registered with `output_reason`.
- Tests prove duplicate registration rejection, task-type normalization, invalid metadata rejection, and handler-result validation.

**Reasoning:**

This is the correct plug-in seam for `tool.invoke`. Registering a new handler with `output_reason="tool action completed"` will cause successful action results to be persisted as a `LineageRecord` through `WorkerRuntimeService.complete` without adding a second output store.

What this does **not** prove: deterministic import/registration for a future handler package is not present. Today handlers are registered because they live in `task_dispatcher.py`.

**Risk:**

- **Duplicate architecture risk:** low if we register handlers here.
- **Authority drift risk:** low if handler returns data and lets dispatcher complete/fail.
- **Schema drift risk:** medium until an action-output schema exists.
- **Tenant leak risk:** medium unless handler validates task tenant against context.
- **Runtime shortcut risk:** low if no direct state mutation is added.

### Finding: Mission-to-runtime task metadata projection

**Status:** Implemented / Partial for action execution

**Evidence:**

- `backend/services/mission_runtime_projection.py` projects selected graph nodes into runtime preview payloads with `runtime_task_type`, input/output contracts, execution constraints, capability references, adapter references, and dependency keys.
- `build_execution_task_payload` persists `runtime_task_type` as `metadata_json["task_type"]` and preserves `capability_reference` and `adapter_reference`.
- `backend/api/routes/mission.py` materializes ready mission graph nodes into planned `ExecutionTask` rows and explicitly does not queue work at materialization time.
- Unit and contract tests cover runtime task materialization, idempotence, cross-tenant hiding, and graph/runtime boundary behavior.

**Reasoning:**

The task graph already carries the metadata needed to choose an executable handler. For the new layer, graph nodes should choose `runtime_task_type="tool.invoke"` and place action-specific input under an agreed action payload key in the task metadata/input contract. Existing projection already carries capability/adapter references that can be validated by the handler.

What this does **not** prove: it does not bind `runtime_task_type` to capability/adapter supported task types at dispatch time, nor does it map capability `required_tools` to executable action registry entries.

**Risk:**

- **Duplicate architecture risk:** low if projection remains unchanged.
- **Authority drift risk:** medium if action metadata is interpreted before queue admission.
- **Schema drift risk:** high unless `tool.invoke` metadata is versioned.
- **Tenant leak risk:** medium if capability/adapter lookups are not tenant-visible.
- **Runtime shortcut risk:** low if materialization remains planned-only.

### Finding: Runtime queue admission and worker admission chain

**Status:** Implemented

**Evidence:**

- `backend/api/routes/mission.py` admits current materialized planned tasks to the queue through `ExecutionCoordinator.queue_task` and records runtime queue admission metadata.
- The same route module has read-only dispatch readiness and governed worker claim/start/run admission surfaces.
- Worker run admission claims an existing queued payload, instantiates `TaskDispatcher`, and executes running tasks through the governed dispatcher bridge.
- Integration tests prove materialized tasks require post-commit queue admission, queue-admission route behavior, worker loop echo execution, dispatcher failure state, lease recovery, dead-letter behavior, and tenant isolation.

**Reasoning:**

The existing runtime path is already staged and queue-authoritative. The action layer should not add a direct “execute capability” API. Its runtime entrypoint is only a queued `ExecutionTask` whose `metadata_json["task_type"]` is handled by the dispatcher.

What this does **not** prove: it does not prove the currently registered handler set is sufficient for real modular actions.

**Risk:**

- **Duplicate architecture risk:** high if any action service creates its own task runner.
- **Authority drift risk:** high if action providers call `complete` or `fail` directly.
- **Schema drift risk:** medium if queue metadata does not preserve action schema versions.
- **Tenant leak risk:** medium if run admission context is not passed through to action providers.
- **Runtime shortcut risk:** high if action execution is allowed before queue admission.

### Finding: Capability registry

**Status:** Declarative Only

**Evidence:**

- `backend/domain/capability.py` documents capabilities as declarative contracts that intentionally do not bind handlers, enqueue work, or execute worker logic.
- `backend/api/routes/capability.py` create/update/list/read routes persist metadata such as `supported_task_types`, `required_permissions`, `required_tools`, `risk_level`, approval requirements, evidence expectations, and execution constraints without queue/runtime effects.
- `backend/repositories/capability_repository.py` provides tenant-visible and conflict-scoped CRUD helpers.
- Unit/API/repository tests cover capability route and repository behavior.

**Reasoning:**

Capability records are the right source of declarative constraints for action validation, but they are not an execution registry. The new action registry must not duplicate capability records; it should map concrete action names to handler callables/providers and validate against capability metadata when references are supplied.

What this does **not** prove: no code registers action handlers from `Capability.required_tools`, and no capability row currently grants runtime authority.

**Risk:**

- **Duplicate architecture risk:** medium if an action registry tries to replace capability records.
- **Authority drift risk:** high if declaring a capability automatically registers an executable tool.
- **Schema drift risk:** medium if required-tools semantics are not normalized.
- **Tenant leak risk:** medium due tenant/global visibility rules.
- **Runtime shortcut risk:** high if capability create/update triggers dispatch.

### Finding: Capability adapter registry and compatibility guard

**Status:** Declarative Only / Partial validation

**Evidence:**

- `backend/domain/capability_adapter.py` documents adapters as declarative contracts that intentionally do not register handlers, enqueue tasks, create execution tasks, or execute tools.
- `backend/api/routes/capability_adapter.py` persists adapter input/output contracts, `execution_mode`, `required_tools`, `side_effect_classification`, and evidence expectations after resolving a tenant-visible capability reference.
- `backend/services/capability_adapter_compatibility.py` validates binding identity, supported task-type subset, risk compatibility, external-side-effect approval metadata, and enabled compatibility.
- Tests cover adapter route and compatibility behavior.

**Reasoning:**

Adapter compatibility is a useful declarative preflight. The new layer should reuse those adapter records as validation metadata. It should not create a second adapter registry, and it should not interpret adapter `execution_mode` as execution authority without a registered handler/action and queue/lease context.

What this does **not** prove: no runtime adapter executor exists, and adapter `required_tools` are not executed by the worker.

**Risk:**

- **Duplicate architecture risk:** high if a new “adapter executor” bypasses dispatcher.
- **Authority drift risk:** high if `execution_mode` changes behavior without runtime gates.
- **Schema drift risk:** high if adapter input/output contracts are not checked against action schemas.
- **Tenant leak risk:** medium if global/tenant adapter visibility is mishandled.
- **Runtime shortcut risk:** high if adapter records are treated as runnable objects.

### Finding: Evidence, outcome, and retrieval surfaces

**Status:** Declarative Only / Partial bridge via lineage task output

**Evidence:**

- `backend/domain/evidence.py` defines durable tenant-owned evidence records and explicitly states they do not score outcomes, promote memory, execute adapters, enqueue work, dispatch workers, or call runtime orchestration.
- Evidence repository/routes provide tenant-scoped persistence/read/update APIs.
- Outcome-review and retrieval-contract domain/repository/routes provide governed contract surfaces for review and recall metadata.
- `WorkerRuntimeService.complete` can append task-output lineage records when the dispatcher supplies validated handler output and an output reason.

**Reasoning:**

There is a durable evidence contract, but the dispatcher currently persists action output as lineage, not `EvidenceRecord`. The minimal slice should return evidence-shaped output inside the handler result and persist it as lineage first. A later phase can add an explicit evidence persistence bridge that converts validated evidence-shaped outputs into `EvidenceRecord` rows.

What this does **not** prove: no current handler automatically creates evidence records, outcome reviews, or retrieval contracts from runtime action output.

**Risk:**

- **Duplicate architecture risk:** medium if a parallel evidence store is added.
- **Authority drift risk:** high if action code writes outcome decisions directly.
- **Schema drift risk:** high until evidence-shaped result schema is stable.
- **Tenant leak risk:** medium on evidence writes.
- **Runtime shortcut risk:** medium if evidence bridge writes before task completion authority.

### Finding: Webhook support

**Status:** Implemented service, missing runtime action handler

**Evidence:**

- `backend/services/webhook_dispatch.py` registers tenant webhook endpoints, requires the webhooks feature, enforces HTTPS URLs, encrypts signing secrets, dispatches matching events by HTTP POST, signs payloads, records deliveries, supports replay, and reports reliability.
- Unit and integration webhook tests cover registration, feature gates, delivery outcomes, timeout/failure behavior, endpoint disable/dead-letter behavior, repository behavior, routes, and replay.

**Reasoning:**

A real webhook service exists and should be reused by a future `webhook.dispatch` action. The missing piece is a dispatcher handler/action wrapper that validates `tool.invoke` metadata, constructs a tenant-scoped `WebhookDispatchService`, calls `dispatch_event`, and returns evidence-shaped output.

What this does **not** prove: there is no `webhook.dispatch` runtime task type or action registration today.

**Risk:**

- **Duplicate architecture risk:** medium if webhook action duplicates delivery logic.
- **Authority drift risk:** high because webhook delivery is an external side effect and must be policy/approval gated.
- **Schema drift risk:** medium around event payload schemas.
- **Tenant leak risk:** high if event dispatch is not tenant-scoped.
- **Runtime shortcut risk:** high if webhooks are sent outside worker queue authority.

### Finding: GTM/CRM catalog and seed metadata

**Status:** Declarative Only

**Evidence:**

- `docs/product/GTM_CAPABILITY_CATALOG.md` states catalog entries are declarative product contracts, not runtime execution grants.
- `alembic/versions/0021_seed_gtm_capability_catalog.py` seeds global `gtm_outbound_email` capability and `gtm_outbound_email_adapter` rows with `supported_task_types`, `required_tools`, approval/evidence expectations, and side-effect classification.
- `tests/contract/saas/test_gtm_catalog_seed_semantics.py` proves seeded shapes and RLS policy cleanup semantics.

**Reasoning:**

The GTM catalog and seed migration are useful examples of capability/adapter metadata, but they do not implement CRM/GTM runtime actions. The action runtime layer should initially avoid a product-specific GTM implementation and prove generic action execution first.

What this does **not** prove: no CRM records provider, GTM message drafting action, lead research action, calendar action, or outbound send action exists.

**Risk:**

- **Duplicate architecture risk:** medium if GTM gets a special runtime path.
- **Authority drift risk:** high if seeded side-effect adapters become runnable without gates.
- **Schema drift risk:** medium as catalog docs and DB rows diverge.
- **Tenant leak risk:** medium if global records are mixed with tenant providers.
- **Runtime shortcut risk:** high for outbound communication actions.

### Finding: Generic action/tool runtime

**Status:** Missing

**Evidence:**

- Repository search found `@register_handler` registrations only for `default`, `force_fail`, and `echo`.
- Repository search found no implementations of `tool.invoke`, `http.request`, `webhook.dispatch`, `record.search`, `record.read`, `sales.research`, `sales.qualify`, `sales.recommend_next_action`, `calendar.create_event`, `crm.research`, or `gtm.message_draft`.
- No `backend/services/tools/` or `backend/workers/handlers/` package currently exists.

**Reasoning:**

The missing layer is not the runtime. The missing layer is a modular action execution package plugged into the existing dispatcher handler registry.

**Risk:**

- **Duplicate architecture risk:** high during implementation if the team mistakes this gap for a runtime gap.
- **Authority drift risk:** high if action code mutates state outside worker-runtime service.
- **Schema drift risk:** high until action input/output contracts are versioned.
- **Tenant leak risk:** high until provider boundaries are tenant-scoped.
- **Runtime shortcut risk:** high if tests do not prove queue/lease/dispatcher execution.

## Plug-in map: current chain and extension points

| Chain point | Current file/function/class | What it already does | How new layer connects | Must not change |
|---|---|---|---|---|
| Mission/task graph | `backend/api/routes/mission.py` mission graph/materialization/admission sections; `backend/services/mission_runtime_projection.py` | Maintains staged mission graph, selected-node, capability, adapter, input/output, and runtime task-type metadata. | Use `runtime_task_type="tool.invoke"` on selected nodes; put action name and payload in a versioned metadata/input envelope. | Do not execute actions during mission intake, graph creation, or readiness checks. |
| Runtime task preview | `build_runtime_task_preview_items` | Projects selected graph nodes into future task previews without creating rows. | Ensure preview exposes `runtime_task_type` and action payload expectations for operator review. | Do not enqueue or dispatch workers from preview. |
| Runtime task materialization | `materialize_mission_runtime_tasks`; `build_execution_task_payload` | Creates planned `ExecutionTask` rows and writes `metadata_json["task_type"]`, capability reference, adapter reference, dependency keys. | Persist `tool.invoke` task metadata unchanged; action handler will read it later. | Do not queue work or call action providers here. |
| `ExecutionTask.metadata_json["task_type"]` | `backend/services/mission_runtime_projection.py::build_execution_task_payload`; `backend/workers/task_dispatcher.py::_task_type_for_task` | Carries dispatch key and normalizes it at execution time. | Register a `tool.invoke` handler under this exact task type. | Do not replace the metadata key or add a second dispatch key. |
| Runtime queue admission | `backend/api/routes/mission.py::_build_runtime_queue_admission`; `backend/services/execution_coordinator.py::queue_task` | Admits planned materialized tasks to queue through coordinator and records admission metadata. | No action-specific queue path. Tool tasks use existing admission. | Do not bypass quota, policy, queue adapter, or task state transitions. |
| Worker claim/start | `WorkerLoop._claim_and_start_task`; `WorkerRuntimeService.claim_next_task`, `heartbeat`, `start_execution` | Claims queue work, creates leases, heartbeats, transitions claimed/running. | No changes; action gets context after task is running. | Do not let action registry claim leases or start tasks. |
| Worker run admission | `backend/api/routes/mission.py::_build_worker_run_admission` | Claims existing queued payload and executes through `TaskDispatcher` for start-admitted running tasks. | `tool.invoke` works here automatically once registered. | Do not create an alternate run-admission executor. |
| `TaskDispatcher` | `backend/workers/task_dispatcher.py::TaskDispatcher.execute` | Loads task, selects registered handler, heartbeats, validates result, completes/fails. | Add handler package imported deterministically by worker startup or dispatcher module. | Do not rewrite dispatcher selection, heartbeat, complete, or fail semantics. |
| Handler registry | `register_handler`; `_HANDLER_REGISTRY`; `_OUTPUT_REASON_BY_TASK_TYPE` | Maps task type to callable and optional output persistence reason. | Register `tool.invoke` with `output_reason` so structured output is stored as lineage. | Do not create a second handler registry. |
| Handler result | `_validate_handler_result` | Requires dict with string keys, non-empty `handler`, and `status="completed"`; optionally JSON serializable. | Action handler returns `{handler:"tool.invoke", status:"completed", action_name, output, evidence, ...}`. | Do not weaken validation for action convenience. |
| Completion/failure | `WorkerRuntimeService.complete/fail` | Owns task terminal transitions, lease release, queue complete/fail, audit, lineage. | Handler returns or raises only. Dispatcher invokes complete/fail. | Do not let action providers call complete/fail or mutate task state. |
| Task output/evidence/outcome surfaces | `LineageRecordRepository` via `WorkerRuntimeService.complete`; `EvidenceRecord`, `OutcomeReview`, `RetrievalContract` routes/repositories | Persists task-output lineage; evidence/outcome/retrieval records exist as separate governed contracts. | Minimal slice: evidence-shaped output in lineage. Later bridge: validated evidence output into `EvidenceRecord`, optional outcome/retrieval records behind explicit gates. | Do not auto-score outcomes or promote memory directly from action handler. |

## Additive architecture plan

### Package layout

Prefer these new modules unless implementation discovery during the slice shows a better in-repo convention:

- `backend/workers/handlers/__init__.py`
- `backend/workers/handlers/tool_invoke.py`
- `backend/services/tools/__init__.py`
- `backend/services/tools/action_registry.py`
- `backend/services/tools/schemas.py`
- `backend/services/tools/local_records.py`
- `backend/services/tools/sales_actions.py`
- Later: `http_actions.py`, `webhook_actions.py`, `calendar_actions.py`.

### Handler registration model

- `backend/workers/handlers/tool_invoke.py` registers exactly one task handler: `@register_handler("tool.invoke", output_reason="tool action completed")`.
- Deterministic registration must happen at worker/API import time. Minimal safe option: import `backend.workers.handlers` once from `backend/workers/task_dispatcher.py` after built-in handlers or from `backend/workers/__init__.py`. This is the one likely existing-file modification, justified because current registration is import side-effect based.
- The handler receives `ExecutionTask` and `TaskHandlerContext`, validates tenant ID, parses a versioned input envelope, validates referenced capability/adapter metadata, invokes an action by name through the action registry, and returns dispatcher-valid JSON.

### Action registry model

- `ActionRegistry` maps canonical action names to immutable `ActionDefinition` objects.
- `ActionDefinition` fields:
  - `name`
  - `schema_version`
  - `handler`
  - `side_effect_class` (`none`, `internal_write`, `external_read`, `external_write`, `external_send`, `external_publish`)
  - `required_permissions`
  - `required_tools`
  - `input_schema` or typed payload validator
  - `output_schema` or typed output validator
  - `evidence_types`
- Registry rules:
  - reject blank names;
  - reject duplicate names;
  - fail closed on missing actions;
  - no dynamic DB-backed action registration in the first slice;
  - default registry built deterministically in code.

### Action input/output contract

Suggested task metadata envelope for `tool.invoke`:

```json
{
  "schema_version": 1,
  "task_type": "tool.invoke",
  "tool_invocation": {
    "schema_version": 1,
    "action": "record.search",
    "input": {},
    "provider": "local_records",
    "idempotency_key": "optional-stable-key"
  },
  "capability_reference": {},
  "adapter_reference": {}
}
```

Handler result shape:

```json
{
  "handler": "tool.invoke",
  "status": "completed",
  "schema_version": 1,
  "action": "record.search",
  "side_effect_class": "none",
  "output": {},
  "evidence": [
    {
      "evidence_type": "action_result",
      "evidence_source": "tool.invoke.record.search",
      "summary": "...",
      "structured_payload": {},
      "confidence": 1.0,
      "collection_status": "collected"
    }
  ],
  "runtime_context": {
    "tenant_id": "...",
    "task_id": "...",
    "lease_id": "..."
  }
}
```

### Sales-side record model

- Local provider records should be tenant-scoped dataclasses/Pydantic models, not a new CRM database schema in the minimal slice.
- Suggested record types: account, contact, opportunity, activity.
- Provider interface:
  - `search_records(tenant_id, record_type, query, filters, limit)`
  - `read_record(tenant_id, record_type, record_id)`
- Local provider should use in-memory fixture data keyed by tenant ID for unit/integration determinism.

### Provider/tool abstraction

- Providers do external or local IO; actions orchestrate provider calls and normalize outputs.
- Providers must receive tenant ID and never default to global tenant state.
- External providers (`http`, `webhook`, `calendar`) must be side-effect classified and gated before use.

### Runtime failure behavior

- Missing action, malformed envelope, invalid provider, invisible capability/adapter, unsupported task type, capability/tool mismatch, and provider errors raise `ValueError` or domain-specific exceptions in the handler.
- `TaskDispatcher` catches exceptions and calls `WorkerRuntimeService.fail`; do not catch failures inside the handler unless converting to a sanitized exception message.
- Handler must not return `status="failed"` because dispatcher validation only accepts `completed`.

### Capability/adapter validation behavior

For `tool.invoke` with references:

1. Resolve `capability_reference.capability_id` or name/version via `CapabilityRepository.get_visible_*` using context tenant.
2. Resolve `adapter_reference.adapter_id` via `CapabilityAdapterRepository.get_visible_for_tenant` when supplied.
3. Verify capability and adapter are enabled.
4. Verify `tool.invoke` or the concrete action name is allowed by `supported_task_types`/`required_tools` policy. First slice should define the exact mapping and tests. Recommended: capability/adapter `supported_task_types` must contain `tool.invoke`; `required_tools` may contain the action name or provider family.
5. Reuse `validate_capability_adapter_compatibility` when both are present.
6. For side-effecting actions, require adapter approval metadata and policy evidence before invocation. First slice should only implement `side_effect_class="none"` sales/local actions.

### Tenant and permission enforcement behavior

- The handler must compare `task.tenant_id` to `context["tenant_id"]` and fail closed on mismatch.
- Use tenant-visible repositories only; do not read foreign rows.
- Runtime route permissions remain enforced by existing API route stages.
- For first slice, action definitions can declare `required_permissions=[]` and side effect `none`; later slices should bridge to existing authorization/policy services for user-initiated admissions.

## Minimal powerful slice

The smallest end-to-end slice should prove a generic action path, not CRM/GTM product execution:

1. Add `backend/services/tools/schemas.py` with strict typed contracts for tool invocation input, action result, evidence-shaped item, and local record models.
2. Add `backend/services/tools/action_registry.py` with deterministic registration and duplicate/missing validation.
3. Add `backend/services/tools/local_records.py` with tenant-scoped in-memory/local fixtures and provider methods for `record.search` and `record.read`.
4. Add `backend/services/tools/sales_actions.py` registering:
   - `record.search`
   - `record.read`
   - `sales.research`
   - `sales.qualify`
   - `sales.recommend_next_action`
5. Add `backend/workers/handlers/tool_invoke.py` registering `tool.invoke` through the current dispatcher registry.
6. Add one deterministic import hook for `backend.workers.handlers` so `tool.invoke` is registered in worker and tests.
7. Tests:
   - action registry unit tests;
   - local provider unit tests;
   - sales action unit tests;
   - tool handler validation tests;
   - dispatcher test for `tool.invoke`;
   - integration test proving a queued `tool.invoke` task executes through the real worker path and stores task-output lineage.

Completion proof for minimal slice: a planned task with `metadata_json["task_type"] == "tool.invoke"`, queued by existing coordinator/queue path and claimed by existing worker runtime path, reaches `completed`, releases its lease, completes queue claim, writes worker audit, and persists JSON-serializable tool output as lineage.

## Full completion roadmap

### Phase 1: Handler package and deterministic registration

- **Goal:** Provide a stable home for dispatcher handlers without changing dispatcher semantics.
- **Files likely created:** `backend/workers/handlers/__init__.py`, `backend/workers/handlers/tool_invoke.py`.
- **Files likely modified:** `backend/workers/task_dispatcher.py` or `backend/workers/__init__.py` for a minimal import hook.
- **Tests required:** handler registration import test; duplicate registration negative test; dispatcher unknown/invalid task type tests remain passing.
- **Risks:** import cycles and duplicate handler registration.
- **Completion proof:** `tool.invoke` appears in `_HANDLER_REGISTRY` exactly once after normal worker imports.

### Phase 2: Tool/action registry

- **Goal:** Add a code-level registry for executable actions, distinct from declarative capability registry.
- **Files likely created:** `backend/services/tools/action_registry.py`, `backend/services/tools/schemas.py`, `tests/unit/tools/test_action_registry.py`.
- **Files likely modified:** none expected.
- **Tests required:** register, duplicate rejection, missing action, blank name, JSON-serializable result validation.
- **Risks:** accidentally creating a second capability registry.
- **Completion proof:** actions invoke by name through the registry and return typed action results.

### Phase 3: Sales-side action pack

- **Goal:** Provide non-side-effecting local actions proving useful modular execution.
- **Files likely created:** `backend/services/tools/local_records.py`, `backend/services/tools/sales_actions.py`, `tests/unit/tools/test_local_records.py`, `tests/unit/tools/test_sales_actions.py`.
- **Files likely modified:** `backend/services/tools/__init__.py`.
- **Tests required:** record search/read, tenant isolation, sales research/qualification/recommendation, invalid payloads, missing records.
- **Risks:** product-specific assumptions creeping into generic slice.
- **Completion proof:** `tool.invoke` can execute all five local/sales actions and return evidence-shaped output.

### Phase 4: HTTP action support

- **Goal:** Add controlled external-read `http.request` action.
- **Files likely created:** `backend/services/tools/http_actions.py`, tests for HTTP action.
- **Files likely modified:** action registry defaults.
- **Tests required:** allowed method/URL validation, timeout, response truncation, deny private network/unsafe schemes if required, side-effect gating for non-GET methods.
- **Risks:** SSRF, secret leakage, external side effects.
- **Completion proof:** safe external-read HTTP action returns evidence-shaped response without bypassing runtime.

### Phase 5: Webhook action support

- **Goal:** Wrap existing `WebhookDispatchService` as `webhook.dispatch`.
- **Files likely created:** `backend/services/tools/webhook_actions.py`, tests.
- **Files likely modified:** action registry defaults only.
- **Tests required:** tenant-scoped endpoint selection, feature gate propagation, successful/failed delivery output, no duplicated webhook service logic.
- **Risks:** external side effects and approval gating.
- **Completion proof:** queued `tool.invoke` calling `webhook.dispatch` uses `WebhookDispatchService.dispatch_event` and records results.

### Phase 6: Calendar action support

- **Goal:** Add `calendar.create_event` behind provider abstraction and policy gates.
- **Files likely created:** `backend/services/tools/calendar_actions.py` and provider interface/tests.
- **Files likely modified:** action registry defaults and policy validation hooks.
- **Tests required:** dry-run/local provider, idempotency key, missing approval, tenant isolation.
- **Risks:** external write side effects and duplicate event creation.
- **Completion proof:** local/dry-run calendar provider executes through worker path with idempotent evidence.

### Phase 7: CRM/GTM adapter compatibility bridge

- **Goal:** Connect capability/adapter metadata to tool/action validation without granting automatic execution authority.
- **Files likely created:** `backend/services/tools/capability_validation.py`, tests.
- **Files likely modified:** `tool_invoke.py` to call validation service.
- **Tests required:** invisible capability/adapter, disabled records, unsupported task type, required-tool mismatch, risk/approval side-effect rejection.
- **Risks:** authority drift from declarative metadata to runtime authority.
- **Completion proof:** referenced capability/adapter records constrain action execution but do not register actions.

### Phase 8: Evidence persistence bridge

- **Goal:** Convert validated evidence-shaped handler output into `EvidenceRecord` rows when explicitly configured.
- **Files likely created:** `backend/services/tools/evidence_bridge.py`, tests.
- **Files likely modified:** `WorkerRuntimeService.complete` only if repository evidence proves lineage-only is insufficient; otherwise call bridge from handler before returning only for side-effect-free cases is not preferred because completion might later fail.
- **Tests required:** evidence row creation, rollback/transaction behavior, tenant scoping, lineage/evidence consistency, no outcome scoring.
- **Risks:** writing evidence before task completion or creating duplicate stores.
- **Completion proof:** task completion and evidence persistence are transactionally understandable and test-backed.

### Phase 9: Outcome review bridge

- **Goal:** Create outcome review records only from explicit action output and policies.
- **Files likely created:** `backend/services/tools/outcome_bridge.py`, tests.
- **Files likely modified:** none or minimal bridge hook after evidence bridge design.
- **Tests required:** review-required actions, rejected/approved states, no direct runtime state mutation from outcome score.
- **Risks:** autonomous outcome scoring and runtime authority drift.
- **Completion proof:** outcome records are created as review contracts only.

### Phase 10: Runtime matrix / authority ledger updates

- **Goal:** Document implemented action-runtime authority only after tests prove it.
- **Files likely modified:** `docs/validation/live-runtime-matrix.md`, `docs/contracts/authority-ledger.v1.yaml`, possibly policy docs.
- **Tests required:** docs contract tests and architecture ledger tests.
- **Risks:** docs overstating implementation.
- **Completion proof:** matrix rows cite passing tests and do not claim unimplemented actions.

### Phase 11: Integration/recovery/dead-letter proof

- **Goal:** Prove action failures remain compatible with existing recovery and dead-letter behavior.
- **Files likely created/modified:** integration tests under `tests/integration/runtime/` and contract tests under `tests/contract/runtime/`.
- **Tests required:** provider exception -> failed task; retry/dead-letter compatibility; lease expiration during action; no duplicate output on retry.
- **Risks:** retries duplicating side effects.
- **Completion proof:** real worker/integration tests show existing recovery paths still govern action tasks.

### Phase 12: Production slicing strategy for PRs

- **Goal:** Keep production changes reviewable and authority-safe.
- **Suggested PRs:**
  1. registry/schemas only;
  2. `tool.invoke` handler + local action pack + tests;
  3. capability/adapter validation bridge;
  4. HTTP external-read support;
  5. webhook support;
  6. evidence/outcome bridges;
  7. docs/matrix/ledger after proof.
- **Risks:** oversized PR hiding authority changes.
- **Completion proof:** each PR has targeted unit, contract, and integration evidence.

## Implementation boundaries

### Allowed

- Add new modular handlers.
- Add new tool/action modules.
- Add local/mock providers.
- Add action registries.
- Add schemas/contracts for action input and output.
- Add tests.
- Add docs/matrix rows only when implementation exists.
- Add a minimal import/registration hook only if required for deterministic handler registration.

### Forbidden unless proven necessary

- Rewriting `TaskDispatcher`.
- Rewriting `WorkerLoop`.
- Changing queue semantics.
- Changing worker lease semantics.
- Changing runtime state-machine transitions.
- Bypassing queue admission.
- Bypassing tenant/auth/permission checks.
- Silently mutating external systems.
- Creating duplicate capability registries.
- Creating duplicate adapter registries.
- Building a separate runtime beside the existing runtime.
- Treating declarative capability records as execution proof without a handler/tool path.

## Exact test plan

### Unit tests

- `tests/unit/tools/test_action_registry.py`
  - registers an action and invokes it;
  - rejects blank action names;
  - rejects duplicate action names;
  - fails closed on missing action;
  - validates action result schema and JSON serializability.
- `tests/unit/tools/test_local_records.py`
  - searches tenant-local records;
  - reads tenant-local records;
  - rejects cross-tenant record reads;
  - returns empty search safely;
  - validates record-type and limit bounds.
- `tests/unit/tools/test_sales_actions.py`
  - `record.search` output shape;
  - `record.read` output shape;
  - `sales.research` evidence-shaped output;
  - `sales.qualify` deterministic score/reason output;
  - `sales.recommend_next_action` deterministic recommendation output;
  - invalid payload negative tests.
- `tests/unit/workers/test_tool_invoke_handler.py`
  - handler parses valid envelope;
  - rejects missing `tool_invocation`;
  - rejects missing action;
  - rejects unknown action;
  - rejects tenant mismatch;
  - validates capability/adapter references when supplied;
  - returns dispatcher-valid `handler/status` result;
  - returns evidence-shaped output.
- Extend `tests/unit/workers/test_task_dispatcher_registry.py`
  - deterministic registration includes `tool.invoke`;
  - output reason is configured for `tool.invoke`.

### Dispatcher and service tests

- Extend or add `tests/unit/workers/test_task_dispatcher_runtime_contract.py`
  - dispatcher completes a running `tool.invoke` task through registered handler;
  - dispatcher persists handler output only when output reason is present;
  - malformed `tool.invoke` payload causes dispatcher fail path.
- Add/extend `tests/unit/services/test_worker_runtime_service_transaction_contract.py`
  - task output lineage remains JSON serializable;
  - failure path does not write action output.

### Integration tests

- `tests/integration/runtime/test_worker_executes_tool_invoke_task_real.py`
  - create planned `ExecutionTask` with `task_type="tool.invoke"` and action `record.search`;
  - queue it through existing coordinator/queue;
  - execute through real `WorkerLoop` or the same real claim/start/dispatcher path used by echo tests;
  - assert task completed, lease released, queue claim completed, audit event written, task-output lineage written with `handler="tool.invoke"` and evidence-shaped output.
- Extend runtime failure tests:
  - unknown action fails task through dispatcher;
  - invalid payload fails task through dispatcher;
  - retry/dead-letter compatibility for repeat action failure if retry policy applies.

### Capability/adapter validation tests

- `tests/unit/tools/test_capability_action_validation.py`
  - missing required capability reference fails when policy requires it;
  - invisible capability fails;
  - invisible adapter fails;
  - disabled capability/adapter fails;
  - adapter/capability mismatch fails;
  - unsupported task type fails;
  - required-tools mismatch fails;
  - external-side-effect action without approval metadata fails.

### Tenant isolation tests

- Local provider cross-tenant search/read tests.
- Handler task/context tenant mismatch test.
- Integration test with two tenants and same record ID proves each tenant sees only its local provider data.

### Evidence/output tests

- Evidence-shaped item schema validation.
- Dispatcher lineage output contains action name, side-effect class, output, evidence list, and runtime context.
- Evidence persistence bridge tests should be added only in the later bridge phase, not the minimal slice.

## First implementation prompt for minimal slice

Use this prompt for the next implementation step:

> Implement the minimal additive Capability Action Runtime slice in `1devteam/ajenda-ai` without replacing runtime authority. Read `PROJECT_SPEC.md`, `backend/workers/task_dispatcher.py`, `backend/workers/worker_loop.py`, `backend/services/worker_runtime_service.py`, `backend/services/mission_runtime_projection.py`, capability/adapter domain/repository/routes, and the existing dispatcher/worker/runtime tests before editing. Add a `tool.invoke` handler through the existing `register_handler` mechanism and preserve `TaskDispatcher`, `WorkerLoop`, queue, lease, state-machine, and materialization semantics.
>
> Create `backend/services/tools/` modules for strict schemas, an action registry, a tenant-scoped local records provider, and local/sales actions: `record.search`, `record.read`, `sales.research`, `sales.qualify`, and `sales.recommend_next_action`. Create `backend/workers/handlers/tool_invoke.py` that registers `tool.invoke` with an output reason, parses a versioned `metadata_json["tool_invocation"]` envelope, validates tenant context, invokes the action registry, and returns a dispatcher-valid JSON result with `handler="tool.invoke"`, `status="completed"`, structured output, and evidence-shaped items. Add only the minimal deterministic import hook needed for handler registration.
>
> Do not create a second runtime, second capability registry, second adapter registry, direct execution API, direct queue bypass, direct lease manipulation, or direct task completion/failure calls from actions. Provider/action failures should raise and let `TaskDispatcher` call `WorkerRuntimeService.fail`.
>
> Add unit tests for action registry, local records, sales actions, tool handler validation, handler registration, and handler-result shape. Add a dispatcher test for `tool.invoke`. Add one integration/runtime test proving an existing queued task executes through the real worker/dispatcher path and persists task-output lineage. Include negative tests for missing action, invalid payload, unsupported task type/action mapping, and tenant mismatch. Run `ruff check .`, `ruff format --check .`, and targeted pytest commands before commit.
