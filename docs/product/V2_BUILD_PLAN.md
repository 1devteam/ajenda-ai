# Ajenda AI v2 Build Plan

**Status:** Preparation baseline  
**Source of truth:** implementation, tests, migrations, and runtime proof

## v2 objective

Make Ajenda’s intelligence loop coherent from user instruction to durable,
evidence-backed outcome:

`instruction → interpretation → context → plan → governed execution → evidence → review`

Every stage must preserve the user’s objective, tenant scope, authority class,
and output contract. A stage may narrow or block work, but may not silently drop
meaning or invent facts.

## v1 baseline

The following are working foundations and remain protected:

- tenant isolation and RLS boundaries
- queue-backed execution and worker lease ownership
- fail-closed policy and external connector gates
- mission composition, task-graph materialization, and runtime admission
- audit, evidence, recovery, and release validation gates
- self-serve auth, billing, customer UI, and standalone internal-brain paths

Known v1 friction is concentrated at the intelligence-contract seams:

- profile context can be narrowed between composition and runtime retrieval
- planner proposals can be structurally valid while semantically underspecified
- deliverable shape is not consistently carried from intent to evidence
- worker execution logs were not visible from the worker entrypoint
- clarification and failure messages can expose the first broken layer rather
  than the complete repair path

## v2 workstreams

### 1. Canonical intelligence envelope

Introduce one versioned envelope shared by interpreter, planner, action input,
runtime output, evidence, and review projections. It must contain:

- original and normalized instruction hashes
- resolved tenant/profile context with provenance
- requested outcomes and material clauses
- explicit assumptions, prohibitions, and unresolved fields
- expected deliverable schema
- artifact lineage and source evidence

Acceptance: a mission can be replayed from the persisted envelope without
reinterpreting or reconstructing missing context.

### 2. Context and profile spine

Make approved business profile, governed memory, internal records, and connector
reads explicit sources with deterministic precedence. Normalize profile facts once;
return missing and conflicting fields rather than empty or synthetic prose.

Acceptance: the “who we are” mission produces the same canonical profile brief in
composition preview, runtime evidence, and the review queue.

### 3. Planner/compiler contract

Separate three contracts:

1. interpreter meaning;
2. planner proposal and artifact bindings;
3. runtime action input/output.

Add semantic validation for dropped clauses, unsupported deliverables, unbound
required inputs, and output-contract mismatches. Provider proposals remain
non-authoritative.

Acceptance: malformed, incomplete, stale, or semantically lossy proposals fail
closed with an actionable blocker and no runtime task.

### 4. Outcome and evidence loop

Define deliverable schemas for research, qualification, profile briefs, drafts,
CRM writes, and sends. Persist evidence and lineage at the point of completion,
then expose a review model that explains what was requested, what ran, what was
blocked, and why.

Acceptance: every completed mission has a machine-readable deliverable, source
evidence, and a complete task/audit lineage; failures identify the failed stage.

### 5. Runtime observability and operations

Standardize structured events across API, materializer, queue admission, worker
claim/start/run, action execution, and recovery. Include mission, task, tenant,
worker, lease, action, and contract-version identifiers.

Acceptance: `docker compose logs` and persisted audit records can answer whether
work was never admitted, queued twice, claimed twice, failed in execution, or
completed with evidence.

### 6. Governed self-selling capstone

After the envelope and evidence loop are stable, implement Ajenda’s own governed
GTM sequence: research target accounts, qualify, prepare outreach, require human
review, send through an authorized provider, and log internal CRM activity.

Acceptance: no external send occurs without explicit authorization, provider
evidence, idempotency protection, and a reviewable mission lineage.

## Delivery order

1. Freeze and version the intelligence envelope.
2. Add contract/parity tests across composition → materialization → worker output.
3. Implement canonical deliverable and evidence schemas.
4. Add semantic planner/compiler validation and actionable blockers.
5. Expand structured runtime observability and failure classification.
6. Build the governed self-selling capstone on those foundations.

## v2 release gates

- all v1 required lint, type, migration, authority, and non-integration tests
- contract-drift and schema-parity checks for every envelope/deliverable change
- tenant-boundary, malformed-input, retry, duplicate, and stale-plan tests
- runtime proof covering queue, lease, evidence, audit, and recovery behavior
- live proof for one read-only mission and one reviewed external-send mission
- no promotion when any stage silently drops a material clause or source

## Explicit non-goals

- bypassing the queue, lease, dispatcher, or policy authority
- adding more catalog abilities before their end-to-end contracts exist
- autonomous external sending or publishing without review and provider proof
- using an LLM response as execution authority or as a substitute for evidence

## Second-pass implementation map

This map ties each v2 workstream to the current code path. It is the change
boundary for implementation; a workstream is not complete when only its model
or UI exists.

| Behavior | Current source of truth | v2 change boundary | Required proof |
|---|---|---|---|
| Interpret instruction | `backend/services/mission_composition/intent_interpreter.py` → `MissionIntent` in `contracts.py` | Additive envelope projection; preserve clause provenance, policy, and readiness semantics | interpreter unit tests, malformed/contradictory clause tests |
| Route business work | `job_catalog.py`, `capability_resolver.py`, `readiness.py` | Validate required inputs/outputs before action selection; never let provider planning replace deterministic safety checks | resolver and readiness contract tests |
| Compile tool inputs | `action_inputs.py`, `plan_compiler.py` | Replace scattered implicit payload assumptions with versioned input/output contracts and explicit binding failures | plan compiler tests for every runtime-bound job |
| Persist composition | `mission_composition/service.py`, `proposal_store.py`, mission intake routes | Persist envelope/provenance atomically with the composition read model; stale threads must remain non-executable | tenant, supersession, and retry tests |
| Build graph | `plan_compiler.py`, `api/routes/mission.py` (`materialize_mission_graph`) | Verify graph nodes, bindings, capability references, and contract versions against the persisted composition | graph materialization and stale-graph tests |
| Materialize tasks | `mission_runtime_task_materialization_service.py`, `mission_bridge/materialization.py` | Preserve one current materialization reference; reject stale or duplicate task projections | materialization idempotency and replacement tests |
| Admit queue work | `mission_runtime_queue_admission_service.py`, `mission_bridge/queue_admission.py`, `api/routes/mission.py` | Keep admission as the sole enqueue authority; make partial admission and duplicate queue outcomes explicit | queue authority, duplicate admission, tenant mismatch tests |
| Claim and execute | `worker_loop.py`, `worker_runtime_service.py`, `task_dispatcher.py`, `handlers/tool_invoke.py` | Add contract IDs and structured stage events without creating a second execution spine | lease, retry, failure, and live runtime proof |
| Run actions | `tools/runtime_authority.py`, `tools/action_registry.py`, action modules | Enforce input schema, tenant scope, side-effect class, credential authority, and output contract at one boundary | action rollout and malformed-input tests |
| Persist evidence | `tools/evidence_bridge.py`, `EvidenceItem` in `tools/schemas.py`, `EvidenceRecord` and repository | Project one canonical durable evidence shape with lineage, trust, limitations, and contract versions | evidence parity and no-synthetic-completion tests |
| Review outcomes | mission read models, evidence routes, audit repository/routes | Add a deliverable/review projection that joins mission → task → evidence → audit without granting authority | read-only review API and lineage tests |
| Profile/context truth | `business_profile_repository.py`, `business_profile_record_sync.py`, `business_context_resolver.py`, `retrieval_actions.py` | Keep one normalized profile snapshot and explicit missing/conflicting fields across preview and runtime | profile brief parity and tenant isolation tests |
| Runtime observability | `backend/app/logging.py`, `start-worker.sh`, worker/API loggers, audit events | Standardize event names and required IDs; do not infer runtime state from logs alone | log contract tests plus persisted audit proof |

### Second-pass corrections to the original plan

- The v2 envelope must be an additive projection around `MissionIntent` and
  `MissionCompositionRecord`; it must not replace either authority boundary.
- Deliverable schemas belong beside action contracts and evidence persistence,
  not only in the planner. A planner may propose a shape, but runtime output and
  durable evidence must validate it independently.
- “Exactly once” is not a safe blanket promise. v2 must prove idempotency per
  action and preserve at-least-once queue semantics with duplicate detection.
- Profile provenance is tenant data and must remain behind the activated tenant
  session; never copy profile facts into global planner state or process caches.
- Observability is diagnostic evidence, not execution truth. Database task state,
  lease state, queue admission metadata, and durable evidence remain authoritative.
- A v2 capstone send is downstream of these contracts; it is not a substitute
  for fixing composition, binding, evidence, and review seams first.
