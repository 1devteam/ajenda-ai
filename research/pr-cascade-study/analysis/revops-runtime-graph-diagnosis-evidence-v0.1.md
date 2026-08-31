# RevOps Runtime / Graph Diagnosis Evidence v0.1

**Status:** post-observation evidence record; not a causal treatment-effect finding  
**Recorded:** 2026-08-31  
**Repository population:** `1devteam/ajenda-ai` only  
**Frozen code boundary for independent verification:** `9a3a3009217d0ea564bd0a04086330a5bc491db5` (merge of PR #496)  
**Relation to prior note:** follows `prospective-revops-graph-evaluation-observation-v0.1.md`; that prospective record is intentionally preserved unchanged.

## 1. Purpose

This document preserves the next chronological observation in the RevOps / graph-evaluation episode after the prospective evaluator-framing note.

It records three distinct evidence layers without collapsing them:

1. **Evaluator self-correction** — the implementing/evaluating LLM explicitly revised its earlier claim that the problem was not a graph-tool problem.
2. **Subsequent real mission runtime report** — a later capture reported the mission/task state after more of the seven-task graph had executed.
3. **Graph-assisted diagnosis** — the evaluator then used graph-selected architecture/code neighborhoods and reported five concrete issues.

The study must distinguish the evaluator's claims from independently verified repository mechanisms. A statement appearing in the evaluator output is not automatically a study finding.

## 2. Source chronology

### 2.1 Earlier prospective state

The prior prospective note was created when only the first task output was available. At that point the defensible position was that the first producer emitted weak/unverified candidates, while the full mission graph, remaining task outputs, final deliverable, and root cause were not yet known.

That note recorded an evaluator-framing concern because the evaluator prematurely characterized the issue as a producer boundary rather than a graph problem.

### 2.2 Evaluator self-correction

In the later supplied capture, the evaluator explicitly identified two mistakes in its earlier reasoning:

- it had reduced "the graph" to the canonical source dependency graph even though the broader graph product can represent or aspire to represent architecture, mission topology, artifact flow, semantic contracts, runtime state, evidence, authority, and proof relationships;
- it had imported the principle "do not expand graph capability unless real use proves a deficiency" into the RevOps diagnosis without first establishing whether the run exposed a graph deficiency.

The evaluator further acknowledged that the first-of-seven-task evidence was insufficient to rule graph causes in or out and that several graph-relevant mechanisms could produce the same symptom.

### 2.3 Later real mission runtime report

The supplied runtime capture identified mission:

- mission id: `4fb6743c-eb06-4f06-bc94-49ae72e576e2`
- objective: Phoenix HVAC prospect research and outreach drafting
- reported mission status: `running`

Reported task states:

| Task | Reported state |
|---|---|
| Web research | Completed |
| Observe contacts | Completed |
| Retrieve current knowledge | Failed |
| Qualify prospects | Completed |
| Lead enrichment | Failed |
| Recommend next action | Queued |
| Email drafting | Queued |

The capture reported that the research task returned real public search results, but its metadata marked `candidates_real: false`; therefore those search results were not sufficient to establish fully verified prospect records.

The capture also reported repeated `claim_deferred_dependencies` events for the two queued descendants and stated that no email-send task existed in the materialized task set, so no outbound email write was attempted.

The mission was reported stuck rather than terminal because failed upstream tasks left descendants queued.

## 3. Evaluator's five post-graph claims

The evaluator reported five issues after graph-assisted inspection:

1. typed dependency semantics are discarded between the business-job catalog and runtime task graph;
2. failed dependencies are classified as pending, causing repeated defer/requeue behavior;
3. structural artifact completion does not establish artifact viability for downstream contracts;
4. knowledge retrieval has a required-input / binding mismatch and weak failure projection;
5. the current canonical graph cannot directly express the complete runtime artifact/causal chain that was needed for this diagnosis.

The following sections independently adjudicate what the frozen repository supports.

## 4. Claim 1 — typed dependency semantics are lost downstream

### 4.1 Repository-observable facts

At the #496 frozen boundary:

- `DependencyKind` is defined as `hard | conditional | optional`.
- `JobDependency` stores `job_key`, `kind`, `required_when_missing`, and `satisfied_by`.
- `BusinessJob` supports typed `dependencies` separately from legacy `depends_on_jobs`.
- `PlannedStepPreview.depends_on` is only `list[str]`; it carries no dependency kind.

The business-job catalog includes concrete typed examples:

- `intelligence.retrieve_knowledge -> research.observe_sources` is `hard`;
- `intelligence.advise_next -> research.observe_sources` is `hard`;
- `intelligence.advise_next -> intelligence.retrieve_knowledge` is `optional`.

The plan compiler's `_resolved_dependency_job_keys()` iterates selected `job.dependencies` and returns the dependency job key whenever the dependency job is present. It does not branch on `dep.kind`.

`compile_planned_steps()` therefore writes all resolved dependency job keys into the same untyped `depends_on` list.

`compile_task_graph_preview()` then emits every one of those edges as:

- `dependency_type: "depends_on"`
- metadata description: `Compiled from business job dependencies.`

### 4.2 Working adjudication

**Code-supported mechanism: HIGH confidence.**

The typed semantic distinction exists at the catalog layer and is not represented in `PlannedStepPreview.depends_on` or the emitted task-graph edge type.

This does not by itself prove that every conditional/optional dependency is wrongly expanded, because job routing/resolution can omit a dependency job before compilation. It does prove that **once a typed dependency is selected into the same composition, the downstream plan/task-graph representation does not preserve its kind**.

### 4.3 Relevance to the observed mission

Because `intelligence.retrieve_knowledge` is an optional dependency of `intelligence.advise_next`, loss of that optionality is a plausible direct mechanism for recommendation being blocked by failed knowledge retrieval.

A mission-record-level reconstruction should still confirm the exact materialized dependency keys before this individual runtime relation is marked fully adjudicated.

## 5. Claim 2 — failed dependencies collapse into pending and can keep descendants queued

### 5.1 Repository-observable facts

`pending_dependency_keys()`:

- reads a task's `dependency_keys`;
- indexes mission tasks by graph node key;
- considers a dependency ready only when the upstream task state is exactly `completed`;
- appends the dependency key to `pending` when the upstream task is missing or in any other state.

There is no separate branch for upstream `failed`, `blocked`, `cancelled`, or `dead_lettered`.

During worker claim, `WorkerRuntimeService.claim_next_task()`:

1. claims the task;
2. calls `pending_dependency_keys()`;
3. if any keys are pending, logs `claim_deferred_dependencies`;
4. transitions the lease to released;
5. transitions the task back to `queued`;
6. stores dependency-deferral metadata;
7. releases the queue lease and returns without execution.

Mission rollup treats queued tasks as open/non-terminal. It does not fail the mission while open tasks remain. Mission terminalization is evaluated only after all graph tasks are terminal.

### 5.2 Working adjudication

**Code-supported mechanism: HIGH confidence.**

The implementation collapses all non-completed upstream states into the same dependency-not-ready path. A descendant of a terminally failed dependency is therefore not automatically terminalized by this path.

Combined with the supplied runtime report of continual `claim_deferred_dependencies`, the observed stuck-running mission is consistent with this mechanism.

### 5.3 Important scope qualification

The code evidence proves the worker/dependency behavior. It does not prove that no separate reconciler, operator action, cancellation path, or later repair can terminalize the descendants. The precise statement is therefore:

> The ordinary claim/dependency path does not distinguish terminally impossible dependencies from temporarily incomplete dependencies and can repeatedly return such descendants to `queued`.

## 6. Claim 3 — structural artifact validation is weaker than downstream viability

### 6.1 Repository-observable facts

Worker completion invokes `_validate_declared_output_contract()` before transitioning a task to `completed`.

For typed composition artifacts, this delegates to `validate_artifact_payload()`.

For per-item artifact schemas, the validator requires the payload to be a list and then validates required fields **for each item that exists**.

If the payload is an empty list:

- it is a list;
- the per-item loop has zero iterations;
- no missing-field errors are emitted.

`QUALIFIED_PROSPECTS_SCHEMA` specifies per-item fields such as company, score, reasons, qualification evidence, and Ajenda relevance, but does not specify a minimum cardinality or identity/evidence predicate that applies to the collection itself.

The runtime input binder separately supports `binding_required`. For actions requiring prospect world state, if the bound prospect list is absent or empty and no permitted fallback context exists, it raises `InputBindingError`.

### 6.2 Working adjudication

**Code-supported mechanism: HIGH confidence.**

At this boundary, runtime artifact validation proves structural shape/field presence for emitted items; it does not prove a non-empty artifact or downstream semantic viability.

The supplied capture's reported sequence—qualification completes with zero qualified prospects, then enrichment fails because no prospects are available—is consistent with this split.

### 6.3 Product-design implication, not yet a study finding

Potential remedies include collection-level predicates such as:

- minimum cardinality;
- verified-identity requirement;
- real-contact requirement;
- provenance/evidence requirement;
- downstream-edge-specific acceptance predicates.

Which predicates belong in artifact schemas, graph edges, mission acceptance, or action contracts is an architecture decision for the implementation PR, not something this research record should prescribe as a proven answer.

## 7. Claim 4 — knowledge retrieval declares observed-contact dependence but receives no upstream artifact binding

### 7.1 Repository-observable facts

The business-job catalog defines `intelligence.retrieve_knowledge` with:

- `required_inputs=("observed_contacts",)`;
- produced output `retrieved_knowledge`;
- candidate action `knowledge.retrieve_current`;
- a `hard` dependency on `research.observe_sources`.

The plan compiler's `_binding_input_path()` explicitly returns `None` for `knowledge.retrieve_current`.

Consequently, when the compiler processes that dependency:

- the ordering dependency can still be added to `depends_on`;
- the input-binding record is omitted.

This is a concrete representation mismatch between a declared required input and the compiler's artifact-binding behavior.

### 7.2 Failure-cause visibility

The supplied capture reported that the knowledge task failed but the ordinary task record did not expose a persisted error code/reason.

Repository inspection supports the observability distinction:

- `ExecutionTask` has status and `metadata_json` but no dedicated error-code or failure-reason column;
- `WorkerRuntimeService.fail()` transitions the task to `failed` and stores the supplied `reason` in the corresponding `AuditEvent.details`.

Therefore the failure reason is not necessarily lost, but it is not part of the ordinary `ExecutionTask` state contract.

### 7.3 Working adjudication

**Required-input/binding mismatch: HIGH confidence.**  
**Exact reason this specific knowledge task failed: NOT YET ESTABLISHED.**  
**Failure-projection/read-model gap: HIGH confidence at the domain-model level; UI/API projection still requires direct route/read-model review if needed.**

The study must not substitute the binding mismatch for the unknown concrete exception without the audit event or equivalent runtime record.

## 8. Claim 5 — graph product representation gap

### 8.1 Canonical graph documentation at the frozen boundary

The canonical dependency graph documentation describes the graph as a repository-level architecture/change-impact instrument combining generated source dependencies with semantic overlay facts.

Documented generated/static node classes include:

- Python modules;
- frontend modules;
- tests;
- migrations;
- database tables;
- network egress sinks.

Documented semantic node classes include:

- runtime;
- security boundaries;
- external services;
- state resources.

The same documentation describes edge semantics for imports, tests, calls, credential/egress authority, tenant boundaries, RLS, state claims/consumption, and capacity reservation.

### 8.2 What is not presently documented as first-class canonical graph vocabulary

The canonical graph documentation does not document first-class node classes for:

- business jobs;
- registered actions;
- artifact contracts;
- materialized mission task instances;
- runtime artifact instances;
- typed dependency predicates/conditions;
- failure causes;
- blocking causal chains.

### 8.3 Working adjudication

**Graph-schema extension opportunity: SUPPORTED CANDIDATE, not yet a fully proven implementation impossibility.**

The evaluator had to traverse from graph-selected repository neighborhoods into mission composition, binder, worker, and artifact code to reconstruct the runtime causal chain. That is useful evidence of current graph-assisted diagnosis.

However, absence from the architecture documentation is not by itself proof that no generated artifact, overlay convention, or separate task-graph structure can represent any of these concepts. The stronger product claim—"the graph cannot represent X"—should be verified against the canonical graph generator/schema/artifact before being converted to a finding.

The defensible present statement is:

> The canonical graph's documented first-class vocabulary does not yet expose the full business-job → artifact → materialized-task → runtime-failure causal chain as one directly queryable model.

## 9. Cross-layer causal picture supported so far

The evidence now supports a multi-layer failure model more strongly than the earlier producer-only hypothesis.

A plausible chain is:

1. weak/unverified research candidates enter the mission artifact flow;
2. downstream structural validation can accept an empty qualified-prospect collection;
3. enrichment can then fail because its required prospect binding is empty;
4. knowledge retrieval has a required-input / binding representation mismatch and fails for an as-yet-unconfirmed concrete reason;
5. recommendation depends on knowledge as an optional catalog dependency, but typed optionality is not preserved in the downstream dependency representation;
6. worker dependency readiness treats the failed upstream task as merely not-completed;
7. the recommendation task is returned to `queued` rather than being allowed to run without the optional input or terminalized according to dependency semantics;
8. queued descendants keep the mission open, so mission rollup remains `running` rather than reaching a truthful terminal state.

Items 2, 5, 6, 7, and the rollup precondition are directly code-supported. Item 4's exact runtime failure cause is not established. Item 1 is runtime-source evidence supplied by the capture. The full chain remains a working causal model until mission-record/audit reconstruction confirms the exact materialized edges and failure reasons.

## 10. Scientific implications for the PR-cascade / graph study

### 10.1 This is evidence of graph usefulness, but not yet evidence of improved repair quality

The graph-assisted inspection appears to have shifted the diagnosis from a local producer-only explanation toward a cross-layer architecture model involving:

- job dependency semantics;
- plan/task graph compilation;
- artifact contracts;
- runtime input binding;
- worker scheduling;
- mission terminalization;
- failure observability.

That is relevant to the study's `reasoning_scope` and `graph_contribution` constructs.

It is **not yet evidence** that the eventual repair will be better, more complete, less cascading, or less regression-prone.

### 10.2 Evaluator self-correction is itself process evidence

The evaluator's later correction of its own earlier graph framing should be preserved because it shows a measurable change in diagnosis after additional runtime/graph inspection.

It should not be interpreted as proof that the graph caused the correction unless the graph commands/artifacts and code-selection pathway can be reconstructed.

### 10.3 The episode may test two graph dimensions simultaneously

The run potentially evaluates:

1. **diagnostic value of the existing canonical graph** — whether it helps locate affected architecture and proof obligations; and
2. **graph-product completeness** — whether the graph itself lacks runtime/business/artifact semantics needed to express the diagnosed system directly.

A positive result on the first dimension can coexist with a deficiency on the second.

### 10.4 Detector maturity must remain separate from product quality

If the graph is expanded after this run to represent business jobs, artifacts, runtime task instances, or blocking causality, that would be a graph-capability intervention. Later improvements in defect visibility must not be counted automatically as lower software defect incidence.

## 11. Alternative explanations that remain admissible

The current evidence does not eliminate the following:

- the particular mission materialization may contain dependency metadata different from the static compiler expectation;
- a runtime reconciling path outside ordinary worker claim may already mitigate some failed-dependency cases;
- knowledge retrieval may have failed for an unrelated action/provider defect even though its binding contract is mismatched;
- a zero-qualified-prospect result may be the semantically correct result for the source evidence, with the true defect located in downstream mission design rather than qualification;
- the graph may already encode some relevant concepts indirectly through generic semantic nodes/edges or noncanonical mission task graphs;
- the evaluator may have found the same code neighborhoods without graph assistance;
- subsequent implementation may fix only one layer and leave the wider chain unresolved;
- subsequent implementation may over-expand scope because of the graph diagnosis.

These alternatives should be tested against the implementation PR and replay evidence rather than removed by narrative preference.

## 12. Required evidence for the next adjudication stage

For the implementation/correction PR that follows this observation, capture:

### 12.1 Exact graph use

- graph commands/queries executed;
- changed-file seeds or runtime concepts used to enter the graph;
- nodes/edges/invariants selected;
- graph-generated impact/proof/completeness/decision artifacts;
- any graph gaps explicitly discovered during the work.

### 12.2 Exact runtime reconstruction

For mission `4fb6743c-eb06-4f06-bc94-49ae72e576e2`, if retained and available:

- materialized task node keys;
- dependency keys per task;
- input bindings per task;
- task metadata/output for all seven tasks;
- audit-event failure reasons for knowledge retrieval and enrichment;
- lineage/evidence records;
- mission acceptance/deliverable state;
- repeated dependency-deferral events and timing.

### 12.3 Repair proof

A strong proof should test semantics, not merely green execution:

- optional dependency failure does not hard-block a dependent action;
- hard dependency failure produces an explicit terminal descendant state with causal provenance;
- conditional dependencies are evaluated against their condition/artifact state;
- task/mission read models expose failure cause sufficiently for diagnosis;
- empty artifacts are either semantically accepted or rejected according to explicit contract, not incidental list shape;
- knowledge retrieval receives the input its job contract declares, or the contract is revised truthfully;
- mission terminalization cannot remain indefinitely `running` solely because an impossible descendant is repeatedly requeued;
- original RevOps mission or controlled equivalent is replayed end-to-end;
- no outbound write occurs unless explicitly present and authorized.

## 13. Working evidence matrix

| Claim | Source report | Repository verification | Current status |
|---|---|---|---|
| dependency kinds lost after catalog | yes | `JobDependency.kind`; untyped `PlannedStepPreview.depends_on`; compiler ignores kind; generic edge | high-confidence mechanism |
| failed dependency treated as pending | yes | `pending_dependency_keys()` only accepts completed; worker requeues on pending | high-confidence mechanism |
| empty artifact can pass structural validation | yes | per-item validator has no collection cardinality predicate | high-confidence mechanism |
| enrichment can fail on empty required binding | yes | binder raises `InputBindingError` when required prospect world is empty | high-confidence mechanism |
| knowledge required input has no compiler binding | yes | catalog requires `observed_contacts`; compiler returns `None` for knowledge input binding | high-confidence contract mismatch |
| exact knowledge failure caused by binding mismatch | implied | failure audit not inspected in supplied repository evidence | unresolved |
| task failure reason absent from ordinary task entity | yes | `ExecutionTask` has no dedicated failure field; worker writes reason to audit event | high-confidence model/projection gap candidate |
| canonical graph lacks full runtime causal vocabulary | yes | architecture docs omit first-class job/artifact/task/failure-chain classes | supported candidate; generator/artifact verification still required |
| graph caused the broader diagnosis | evaluator claims graph use | exact graph query trace not yet preserved here | unresolved contribution magnitude |
| graph-assisted repair will reduce cascade risk | not yet tested | no repair/replay/downstream window yet | untested |

## 14. Non-findings

This record does **not** establish that:

- the graph is superior to non-graph development;
- the graph caused every issue to be found;
- the graph should necessarily be expanded in exactly the evaluator's proposed form;
- the knowledge task failed because of the observed binding mismatch;
- every optional/conditional dependency is currently broken;
- the qualification task was wrong to produce zero prospects;
- the eventual repair is complete;
- the eventual repair will avoid corrective descendants;
- the prior evaluator framing was intentional bias.

## 15. Current research classification

This episode should remain classified as:

- **graph-assisted diagnostic observation:** yes;
- **cross-layer reasoning-scope expansion candidate:** yes;
- **graph-schema deficiency candidate:** yes;
- **product/runtime defect evidence:** yes, for the independently verified mechanisms above;
- **causal graph treatment effect:** not established;
- **repair-quality outcome:** not yet observable;
- **cascade-prevention outcome:** right-censored / not yet observable.

The correct next step is to preserve the implementation PR and replay evidence, then compare predicted scope, actual changed scope, proof topology, residual findings, and later corrective descendants without requiring a graph-positive result.
