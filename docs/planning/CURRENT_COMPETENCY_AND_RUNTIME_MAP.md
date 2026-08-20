# Ajenda current competency and runtime map

**Prepared for:** Obex Blackvault  
**Prepared:** 2026-08-18  
**Implementation baseline:** `main@7ccadea5a9da7700ccf9b0ccd6087c027bff9a12` plus the audited
planning/validation branch  
**Purpose:** establish what Ajenda can actually understand, decide, execute, observe, and learn
before selecting a V1 finish line

## 1. Executive answer

Ajenda's strongest competency is **governed execution of an already well-formed task**. Its weakest
competency is **turning an unfamiliar, compound business request into a correct, adaptive sequence
of tasks and a verified final business outcome**.

The codebase has substantial runtime, policy, evidence, action, tenant, and Knowledge machinery. It
does not yet combine those pieces into a generally competent worker. Today:

- known intents can be mapped deterministically into a bounded job/action catalog;
- fixed vertical templates can materialize known research/email/social task shapes;
- admitted `tool.invoke` work can run through queue, lease, dispatcher, credential, action, and
  evidence gates;
- individual read, research, drafting, CRM, provider, Decision, analysis, and Knowledge actions
  exist;
- durable evidence and learning artifacts can be produced;
- but complex decomposition, typed cross-step artifact flow, outcome-grounded replanning,
  autonomous advancement, and real multi-agent collaboration are incomplete or absent.

The former synchronous HTTP claim/start/run authority has been removed. Its POST routes and
compatibility services now fail closed with HTTP 410, while historical GET readbacks remain.
Daemon `WorkerLoop`/`WorkerRuntimeService` is the sole claim/start/run authority.

## 2. How competency is graded

This map does not assign a synthetic percentage. Each competency is classified from implementation
and exact-path proof:

- **Proven:** the implementation exists and a representative canonical runtime path is tested.
- **Bounded:** it works for an enumerated schema/catalog/template, not unfamiliar general cases.
- **Partial:** useful components exist, but the path does not produce the complete claimed outcome
  or lacks required runtime/provider/failure proof.
- **Absent:** the named product behavior is not implemented, even if related records or docs exist.
- **Unsafe to claim:** behavior exists, but known authority, isolation, retry, or product-contract
  gaps prevent a production claim.

These labels describe scope and proof, not code quality or business value.

## 3. Current competency breakdown

| Competency | Current level | What works now | What prevents a stronger claim |
|---|---|---|---|
| Tenant-scoped task execution | **Proven, with release blockers** | Queue-backed `ExecutionTask`, DB lease, single daemon dispatcher spine, action result, lineage/evidence | Queue/DB orphan and recovery proof gaps; incomplete RLS/RBAC |
| Known-intent interpretation | **Bounded** | Deterministic canonical outcomes, clause checks, target/location/quantity extraction, clarifications | Fixed vocabulary/patterns; unfamiliar clauses fail or require restatement; no general semantic planner |
| Mission/job decomposition | **Bounded/partial** | Fixed job catalog, dependency expansion, planned steps, graph preview, vertical templates | No model-backed decomposition into verified typed jobs for unfamiliar compound prompts |
| Action selection | **Bounded** | Resolver selects registered actions against known jobs, charter, readiness, and credentials | Catalog coverage is not business know-how; no measured selection quality across a held-out vertical corpus |
| Cross-step dataflow | **Partial** | `mission_input_binding` can rebind declared upstream outputs for `tool.invoke` dependencies | No complete, versioned artifact contract across arbitrary graphs; final deliverable assembly is not generally proven |
| Tool/action execution | **Proven for representative actions** | 48 canonical registered actions, Pydantic validation, ability-manifest alignment, credential/runtime authority, evidence enforcement | Provider maturity varies; some actions are fallback/example/unconsumed; ability exposure is not the complete registry boundary |
| LLM generation/reasoning | **Partial and narrow** | OpenAI-compatible text generation is used in selected drafting paths; deterministic template fallback exists | LLM interface is text-only; no structured planning/tool loop; provider errors silently fall back to template text; no planner evaluation corpus |
| Business context and internal memory | **Bounded/partial** | Business Profile, internal records, hybrid retrieval, document/Knowledge artifacts, tenant-scoped context | Retrieval authorities are fragmented; context relevance does not itself establish truth; no complete prompt-to-memory-to-outcome product proof |
| Decision support | **Bounded** | Typed decision/recommendation and Knowledge-informed support actions preserve explicit criteria and evidence lineage | Inputs/weights remain caller-defined; Decision Support does not plan or execute; outcome measurements can be caller-supplied |
| Outcome evaluation | **Partial** | Evaluation and learning-signal actions validate shape, chronology, and lineage and emit evidence | Business measurements are not generally observed independently; `OutcomeReview` is not the evaluator's input; success is not automatically tied to requested deliverables |
| Knowledge learning loop | **Partial** | Qualification, durable learning history, consolidation, ledger, retrieval, applicability, and informed-decision components exist | Low-level caller-authored qualification remains; not every stage has worker-backed proof; no scheduler closes the loop automatically |
| Autonomous continuation/replanning | **Partial to absent** | Bounded temporal advancement components and individually queueable actions exist | No general observe-gap-replan controller; no mission-wide budget/no-progress/cycle semantics across a complete vertical |
| External effects | **Unsafe to claim broadly** | Side-effect classes, credential authority, authorization envelopes, and some action-specific durable claims exist | Several writes/sends can replay ambiguously; generic HTTP/webhook/provider guarantees are incomplete; self-issued authorization paths exist |
| Swarming/multi-agent collaboration | **Absent** | Fleet and agent rows, quotas, assignment field, states, lineage/audit for provisioning | No role-enforced scheduler, artifact exchange, collaboration protocol, aggregation, fleet outcome rollup, or multi-agent runtime proof |
| Final business deliverable | **Partial** | Individual actions produce structured outputs/evidence; drafts/documents can be persisted | No universal mission deliverable contract or evaluator proving the compound prompt was satisfied end to end |
| Customer product loop | **Implemented but unsafe to call production-ready** | Signup, verification, keys/session, billing, ability launch, task status UI | Bootstrap/browser credential exposure, partial paid gate, Stripe failure handling, `/dev`, ingress, admin, RBAC/RLS gaps |

## 4. What “runtime” means in Ajenda

A runtime is not the model, the Brain label, the prompt, the capability catalog, or the agent
persona. It is the **authoritative machinery that turns admitted intent into controlled state
transitions, computation or external effects, and durable outcomes**.

For Ajenda, a complete runtime owns or coordinates:

1. **Admission:** decide whether a tenant task may enter execution under auth, plan/quota,
   governor, policy, review, task-state, and payload rules.
2. **Queue authority:** create one durable execution intent and make its DB/queue identity
   reconcilable.
3. **Claim:** atomically assign eligible work to an owner.
4. **Lease:** establish and maintain exclusive, time-bounded execution ownership.
5. **Start:** transition only an owned, eligible task into running state.
6. **Dispatch:** select the registered handler for the declared task type.
7. **Tool authority:** validate action schema, tenant, capability/adapter, side effect,
   authorization, credentials, and dependency inputs before invoking code.
8. **Execution:** perform internal computation/read/write or an authorized provider interaction.
9. **Terminal persistence:** complete, fail, dead-letter, or block with owned lease semantics.
10. **Proof:** persist lineage, evidence, records inspected/changed, audit, queue result, limitations,
    and recovery-relevant state.
11. **Recovery:** reconcile expired, partial, missing, duplicated, or ambiguous work without losing
    the task or replaying an uncertain external effect.

Planning, Knowledge, and Decision Support can inform what work should be proposed, but they are not
runtime authority unless they also claim/start/dispatch/complete work. Declarative capabilities and
agent records describe boundaries; they do not become executors.

## 5. How the parts currently produce “intelligence”

Ajenda's intelligence is distributed across layers rather than owned by one Brain process:

```text
User instruction / explicit task
  → Business Profile + request context
  → Mission Composition interpreter
  → canonical outcomes and business jobs
  → capability/action resolver + readiness/charter checks
  → declarative mission plan and task graph
  → runtime task materialization
  → admission policy/governor/quota/review
  → queue + lease + dispatcher
  → ToolRuntimeAuthority
  → registered action
       ├ deterministic code / internal records / retrieval
       ├ optional LLM text generation
       └ credentialed external provider
  → ActionResult + EvidenceItem
  → lineage/evidence/outcome artifacts
  → optional evaluation/learning-signal/consolidation/retrieval
  → bounded Decision Support for a later explicitly queued action
```

### 5.1 Business Profile and context

This supplies tenant-approved facts and internal context. It helps actions avoid operating without
company identity, products, or existing records. It improves relevance; it does not independently
reason, plan, or prove that retrieved facts remain true.

### 5.2 Mission Composition

The interpreter normalizes supported phrases into canonical outcomes, extracts structured fields,
identifies prohibitions/approval clauses, and requests clarification for unmatched material clauses.
The job catalog and resolver expand known dependencies and select known action candidates. The plan
compiler produces a declarative graph. This is Ajenda's current “know what the user means” layer,
but it is bounded by authored vocabulary and jobs.

### 5.3 Vertical templates and ability manifests

Templates and manifests encode known task shapes, risk, side effects, inputs, providers, and
readiness. They are important know-how scaffolding. They do not understand a new business process,
adapt a plan from results, or execute anything by themselves.

### 5.4 Admission, queue, lease, and dispatcher

These layers do not create semantic intelligence. They make proposed intelligence **operationally
trustworthy** by enforcing when work may run, who owns it, which handler receives it, and how
completion/failure is persisted. Without them, a clever plan is an unsafe suggestion rather than a
governed worker.

### 5.5 ToolRuntimeAuthority and ActionRegistry

`ToolRuntimeAuthority` binds upstream inputs, validates tenant/action/capability/side-effect and
credential constraints, builds a lease-scoped runtime context, invokes the registered action, and
returns structured output/evidence. The registry is where Ajenda's practical skills live. A large
registry provides breadth of operations, not the orchestration competence to combine them correctly.

### 5.6 LLM provider

The current LLM layer accepts a system prompt and user prompt and returns text from an
OpenAI-compatible chat-completions endpoint. When configuration is absent or generation raises an
exception, it returns a deterministic template fallback. This supports drafting, but it is not a
structured planner, tool-using reasoning loop, evaluator, memory controller, or swarm coordinator.

### 5.7 Evidence, outcome, Knowledge, and Decision Support

Action evidence establishes what a task reports it inspected, changed, or produced. Evaluation and
learning actions can transform properly linked artifacts into durable Knowledge. Retrieval and
applicability can bring relevant Knowledge into Decision Support. Decision Support remains advisory
and does not enqueue or authorize execution. This separation is safe, but the loop advances only
when another task is explicitly queued and some outcome inputs are still caller-authored.

### 5.8 Customer UI and control plane

The UI exposes signup, billing, tasks, credentials, CRM, missions, reviews, and settings. It is the
human context/approval/progress surface, not the source of intelligence. Today it does not yet
present one coherent complex-prompt → clarification → plan → artifacts → replan → final deliverable
experience.

## 6. The single runtime-authority spine

### 6.1 Runtime spine A — daemon worker (the operational runtime)

```text
ExecutionCoordinator / mission admission
  → tenant queue payload
  → WorkerLoop polls tenant(s)
  → WorkerRuntimeService.claim_next_task
  → queue claim + DB claimed state + WorkerLease
  → heartbeat + start_execution
  → TaskDispatcher.execute
  → handler / ToolRuntimeAuthority / action
  → WorkerRuntimeService.complete|fail
  → evidence, lineage, lease release, queue terminal result
```

**Real contribution:** asynchronous production execution, tenant scheduling, queue consumption,
lease ownership, liveness, dispatcher execution, and terminal persistence. This is the spine that
can scale through worker processes and should remain the sole claim/start/run authority.

**Intelligence contribution:** none by itself. It faithfully and safely executes the task and action
chosen upstream. Its value is reliability, isolation, and proof.

### 6.2 Removed HTTP mutation spine

```text
POST worker-claim-admission → HTTP 410
POST worker-start-admission → HTTP 410
POST worker-run-admission   → HTTP 410
GET readbacks               → historical metadata only
```

The mutation authority and synchronous dispatcher were removed. Compatibility classes remain only
to fail closed for older importers. Read models may expose historical receipts, but cannot claim,
start, lease, dispatch, complete, or fail work. The runtime authority inventory must remain free of
`competing_http_spine` entries.

## 7. Where intelligence breaks down on a complex prompt

For a request such as “research a market, select the best prospects, draft personalized outreach,
wait for my approval, send it, update CRM, monitor replies, and adjust the next step,” Ajenda can
execute several individual actions. The end-to-end competency breaks at these boundaries:

1. **Semantic coverage:** every material clause may not map to the fixed canonical outcome/job
   vocabulary.
2. **Plan correctness:** no evaluated model planner constructs and justifies the complete graph.
3. **Typed handoff:** research results are not universally bound into qualification, drafting,
   approval, delivery, CRM, and monitoring through versioned artifact contracts.
4. **Authority provenance:** launch/materialization can manufacture authority artifacts instead of
   consuming independently approved grants.
5. **External-effect certainty:** a crash or timeout can leave some sends/writes ambiguous and
   unsafe to retry.
6. **Outcome truth:** task completion/evidence does not always prove the requested business result.
7. **Continuation:** no canonical scheduler observes the result and queues the correct next stage.
8. **Replanning:** no general controller detects a gap, revises an immutable graph within budget,
   invalidates affected approvals, and re-enters admission.
9. **Aggregation:** no general mission-level deliverable assembler proves all requested outputs are
   present and consistent.
10. **Collaboration:** fleet/agent records do not coordinate specialist roles or artifacts.

This explains why adding more actions alone has not made Ajenda feel competent. The missing value is
mostly in orchestration, typed artifacts, evaluation, and bounded continuation—not in another
execution runtime.

## 8. Implication for the V1 choice

- Choose Runtime Foundation only if the product is an execution API; it does not close the
  competency gap.
- Choose Brain Operator if a safe evidence-backed copilot is sufficient; it closes interpretation
  and deliverable assembly only for a bounded read/internal set.
- Choose Single Vertical Worker to close the largest practical competency gap without first solving
  distributed agent coordination.
- Choose Vertical Swarm only if collaboration itself is the product promise; it must build on a
  proven single vertical and the converged daemon runtime.
- Choose Horizontal Platform only after multiple verticals have independent outcome proof.

The recommended V1 remains **Single Vertical Worker**, because it forces Ajenda to demonstrate the
entire intelligence chain—interpretation, planning, action selection, artifact flow, governed
execution, evaluation, bounded replanning, and final deliverable—within one measurable business
domain.

## 9. Proof still required before changing these labels

1. Run the daemon-versus-HTTP bridge race/fault matrix on real PostgreSQL/Redis.
2. Build and seal the first vertical prompt/deliverable corpus with numeric owner thresholds.
3. Trace every selected vertical action through provider/credential/effect guarantees.
4. Prove HTTP prompt through final deliverable across two tenants on the canonical worker path.
5. Prove evidence-grounded evaluation and bounded replan/stop behavior.
6. If swarming is selected, prove role-bound parallel/dependent work, typed handoffs, aggregation,
   fairness, restart, and no third runtime.

Until those artifacts exist, this map is an implementation-grounded readiness assessment—not a
claim that the corresponding V1 has shipped.

## 10. Will the recommended V1 produce the coherent, powerful Ajenda system?

**Conditional yes—but the recommendation is a delivery strategy, not proof that the current layers
already compose effectively.** A Single Vertical Worker V1 is the correct forcing function because
it requires every layer to cooperate on one measurable outcome. It will not succeed if the team
only adds prompts, actions, templates, or another coordinator around the current seams.

Ajenda can preserve its governance model and still become powerful. Governance must be implemented
as a coherent contract pipeline around intelligence, not as disconnected checks that erase context,
duplicate decisions, or require manual approval at every step. The target relationship is:

```text
Intelligence proposes and explains
  → deterministic contracts validate and constrain
  → policy decides eligibility and review
  → one runtime executes with lease ownership
  → evidence observes the result
  → outcome evaluation measures the requested deliverable
  → Knowledge informs a bounded next proposal
```

No intelligence layer should directly claim a queue payload, create execution authority, or treat
its own output as independent truth. Conversely, governance should not rewrite the planner's
business objective, silently drop material clauses, or force low-risk internal reasoning through a
human review intended for external effects.

### 10.1 What can remain

These foundations should be extended rather than replaced:

- tenant envelope, RLS direction, RBAC model, policy/governor boundary, and audit/evidence intent;
- `ExecutionTask`, mission plan/task graph, queue adapter, DB lease, daemon worker,
  `TaskDispatcher`, and `ToolRuntimeAuthority` execution spine;
- action registry, ability manifests, credential authority, side-effect classification, and
  provider-specific action modules;
- Business Profile, internal records, evidence lineage, Knowledge ledger, applicability, and
  Decision Support separation;
- Mission Composition's fail-closed material-clause and clarification behavior;
- fleet/agent records as future role/accountability projections, not executors.

### 10.2 What must change before the layers work as one system

1. **One canonical semantic contract:** objective, constraints, prohibitions, deliverables, success
   criteria, budgets, approvals, and material-clause coverage must survive instruction → plan → graph
   → task → evidence → outcome without being renamed or reconstructed differently by each layer.
2. **One runtime authority:** remove synchronous HTTP claim/start/dispatch ownership. Preserve its
   previews and receipts as read/trigger contracts fulfilled by the daemon spine.
3. **Structured planner boundary:** add evaluated model-backed decomposition behind typed output.
   Planner output remains a proposal; deterministic schema/catalog/policy/credential/budget checks
   decide whether it can materialize.
4. **Typed artifact fabric:** every graph edge must declare the producer output, consumer input,
   schema/version, tenant/mission/graph identity, freshness, redaction, and optional/required
   semantics.
5. **Mission deliverable contract:** define what the user must receive, not merely which tasks must
   complete. Aggregate artifacts and limitations into a versioned final result.
6. **Evidence-grounded outcome authority:** measure success from canonical observations/provider
   receipts and deliverable checks. Caller assertions and model judgments may be hypotheses or
   labeled assessments, not observed facts.
7. **Bounded advancement and replanning:** add an observe → evaluate gap → propose revised immutable
   graph loop with step/replan/cost/time/provider budgets, no-progress/cycle stops, approval
   invalidation, and normal re-admission.
8. **Knowledge composition:** make outcome-derived learning the production qualification path;
   retrieve and test applicability at planning/decision time without letting Knowledge enqueue,
   authorize, or recursively validate itself.
9. **Independent authorization provenance:** planning/materialization may reference grants but must
   not mint approval for its own external actions. Approval must bind tenant, principal/policy,
   action/resource, payload or graph version, expiry, and revocation.
10. **External-effect certainty:** every enabled vertical write/send must use a proven provider
    idempotency contract or enter durable `effect_unknown` without blind replay.
11. **Risk-proportional governance:** low-risk internal thought/read/draft work should advance within
    explicit budgets; external writes/sends/publishes and policy-defined sensitive decisions should
    stop at durable review. Governance remains intact without making every reasoning step manual.
12. **One product state model:** the UI must expose objective, assumptions, clarification, plan,
    connected-system readiness, review, progress, artifacts, evidence, replan history, budget, final
    deliverable, and limitations from the same durable contracts used by runtime.

### 10.3 Governance changes are required, but governance must not be weakened

The required changes are mostly **consolidation and placement**, not removal:

| Current problem | Required governance change | Invariant retained |
|---|---|---|
| Policy/governor/review checks differ by admission path | One re-entrant admission decision used for initial, approved, retry, recovery, and replan work | Every executable task is policy-eligible |
| HTTP and daemon own claim/start/run | Daemon owns execution; HTTP becomes request/readback | Queue and lease authority remain mandatory |
| Ability/materialization can self-issue authority | Independent versioned grants referenced by plans/tasks | Side effects require explicit authority |
| Boolean review intent is inconsistently enforced | Review decision binds task/graph payload hash and invalidates on change | Reviewed work cannot mutate after approval |
| Provider timeout can be ambiguous | Durable effect receipts and reconciliation | No blind duplicate external mutation |
| Missing RLS/RBAC boundaries | Forced RLS plus explicit repository predicates and route permissions | Tenant isolation at every layer |
| Knowledge can accept caller-authored qualification | Canonical learning history from runtime evidence | Knowledge never becomes self-authenticating policy |

### 10.4 How power and governance reinforce each other

When correctly composed, governance increases capability:

- typed constraints give the planner a smaller, more reliable search space;
- capability/provider readiness prevents plans that cannot execute;
- durable artifacts let downstream reasoning use exact upstream results;
- evidence lets evaluators distinguish task completion from outcome success;
- effect receipts permit safe recovery instead of disabling all retries;
- bounded autonomy lets low-risk work continue without constant human intervention;
- explicit review points let high-risk missions advance up to the decision boundary;
- lineage and graph versions make replanning possible without losing what already succeeded;
- tenant budgets and worker fairness allow controlled scale.

The power does not come from bypassing governance. It comes from making governance machine-readable
enough that the planner, runtime, evaluator, and Knowledge layers share the same boundaries.

### 10.5 Definition of coherent vertical intelligence

The recommended V1 is coherent only when one selected vertical demonstrates all of the following in
one traceable run:

1. every material user clause appears in the typed mission contract;
2. the plan selects only available, authorized, schema-compatible actions;
3. every task enters through the one admission and daemon runtime spine;
4. every downstream input is bound to a valid upstream artifact or explicit user input;
5. low-risk stages advance automatically within budget;
6. high-risk stages stop at the correct durable review boundary;
7. provider effects are confirmed, safely retryable, or visibly unknown;
8. the final deliverable is assembled and checked against success criteria;
9. limitations and partial failures are visible rather than hidden behind `completed`;
10. outcome evidence may inform a bounded replan and later Knowledge, but never authorizes itself;
11. tenant, authority, cost, time, and lineage invariants remain intact;
12. the same mission can be explained and reconstructed from durable records after worker/API
    restart.

If any of these are missing, Ajenda may have useful components, but it does not yet have a coherent
vertical intelligence system.
