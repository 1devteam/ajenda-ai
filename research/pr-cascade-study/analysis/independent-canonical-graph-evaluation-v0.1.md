# Independent Canonical Graph Evaluation v0.1

**Status:** independent evaluator pass; evidence review, not a treatment-effect finding  
**Repository:** `1devteam/ajenda-ai`  
**Frozen product boundary:** PR #496 head `b8595583c7ece455eae8c452b050b5af708df29d`; merged main boundary `9a3a3009217d0ea564bd0a04086330a5bc491db5`  
**Canonical graph workflow run:** `33299501967` (`Architecture — Canonical Dependency Graph`, successful)  
**Artifact:** `canonical-dependency-graph`, artifact id `9728467919`  
**Artifact digest reported by GitHub:** `sha256:c4d4b7b407523628c02bda9423c3e36b3fee03c75586d556210d6acd0330b206`  
**Purpose:** independently evaluate the RevOps runtime diagnosis against Ajenda's exact canonical graph artifact and source/test contracts, without relying on the implementing/evaluating LLM's description of what the graph showed.

---

## 1. Independence and contamination control

This review was initiated because the implementing/evaluating LLM had already made a premature statement that the RevOps defect was "not a graph-tool problem" and later reversed that framing after being instructed only to use the graph to scope the issue.

The correct scientific response is not to assume either framing is right. This pass therefore:

1. downloads the exact successful canonical graph artifact produced for the PR #496 head;
2. inspects the graph's actual node/edge vocabulary and generation scope;
3. applies the graph's own traversal semantics to the source modules implicated by the runtime symptom;
4. checks the selected/directly related tests;
5. reads source only after graph scope is established;
6. records where a mechanism is graph-native versus source-derived;
7. preserves unresolved runtime-instance claims as unresolved.

The user-supplied mission logs remain source-reported runtime observations. This evaluator does not have direct access to the local Ajenda database/API for mission `4fb6743c-eb06-4f06-bc94-49ae72e576e2`, so exact task payloads and audit rows are not silently reconstructed.

---

## 2. Exact graph artifact provenance

The PR #496 head has a successful canonical-graph workflow run:

- workflow run: `33299501967`
- workflow: `Architecture — Canonical Dependency Graph`
- run number: `234`
- conclusion: `success`
- head branch: `feat/revops-mission-deliverable-assembly`
- head SHA: `b8595583c7ece455eae8c452b050b5af708df29d`

The workflow completed all graph stages successfully:

- build graph;
- graph/semantic inventory/impact/proof/completeness/decision tests;
- change-impact analysis;
- proof selection;
- completeness audit;
- architecture-decision composition;
- artifact upload.

The downloaded artifact contains:

- `docs/architecture/dependency-graph.v1.json`
- `artifacts/graph-impact-report.json`
- `artifacts/graph-proof-manifest.json`
- `artifacts/graph-completeness-report.json`
- `artifacts/graph-architecture-decision.json`

This is the authoritative frozen graph input for this independent evaluation.

### 2.1 Discrepancy with the other evaluator's stated graph size

The other evaluator reported a "current generated graph" of:

- 1,239 nodes
- 3,717 edges

The exact PR #496 canonical workflow artifact contains:

- **1,265 nodes**
- **3,818 edges**

Difference:

- +26 nodes in the frozen canonical artifact
- +101 edges in the frozen canonical artifact

This does **not** prove the other evaluator inspected an invalid graph. It may have used a locally regenerated artifact from a different working-tree state. It does prove that its numeric statement cannot be treated as provenance for the frozen #496 canonical artifact used by this study.

---

## 3. Exact graph composition

Graph schema version: `1.2`.

### 3.1 Node counts by type

| Node type | Count |
|---|---:|
| `test_module` | 497 |
| `python_module` | 410 |
| `python_function` | 129 |
| `frontend_module` | 109 |
| `migration` | 43 |
| `database_table` | 37 |
| `external_service` | 15 |
| `network_egress_sink` | 13 |
| `state_resource` | 7 |
| `runtime` | 3 |
| `security_boundary` | 2 |
| **Total** | **1,265** |

### 3.2 Important edge counts

The graph contains 3,818 edges. The dominant relationships are:

- `imports`: 1,687
- `tests`: 1,575
- `defined_in`: 129
- `calls_function`: 116
- `tests_function`: 81
- `creates_or_alters_table`: 58
- `stored_in`: 37
- `tenant_data_boundary`: 32
- `rls_enforced`: 24
- `network_call`: 13
- `direct_network_egress`: 12

There are smaller semantic/control relationships for runtime execution, lifecycle authority, credential authority, egress authority, state ownership, admission, retry, persistence, and related architecture facts.

### 3.3 Function-layer scope

The graph's own `generated_from` metadata states:

```text
selective_function_layer = ["backend/services/mission_composition/**/*.py"]
```

All 129 `python_function` nodes are in `backend/services/mission_composition/`.

Consequences for this incident:

- `plan_compiler.py`, `job_catalog.py`, `artifact_schemas.py`, deliverable code, and related composition files receive function-level representation;
- `worker_runtime_service.py` is module-level only;
- `services/tools/mission_input_binding.py` is module-level only;
- `services/tools/knowledge_actions.py` is module-level only;
- GTM and sales action handlers are module-level only.

Thus the graph has materially different diagnostic resolution across the exact failure path.

---

## 4. What the canonical graph can and cannot represent directly

### 4.1 Directly represented classes relevant to the incident

The graph can directly represent:

- source modules and selected mission-composition functions;
- tests and test-to-source relationships;
- API/worker runtimes;
- security boundaries;
- state resources;
- external services;
- DB tables and migrations;
- egress sinks;
- architecture invariants and semantic findings.

### 4.2 Absent first-class runtime/business concepts

The exact frozen graph contains zero node IDs with first-class prefixes/concepts for:

- `job:*`
- `artifact:*`
- `task:*`
- `mission:*`
- `action:*`
- `ability:*`
- `failure:*`
- `cause:*`
- causal `blocking:*` chains

The semantic overlay likewise does not define an explicit composition-artifact/runtime-task dataflow chain.

This does not mean these concepts cannot be inferred indirectly from module relationships or source code. It means the canonical graph cannot currently express the specific runtime statement:

> mission task A produced artifact X, edge contract Y required predicate P, task B failed, therefore task C is causally blocked by B under dependency kind K.

as a first-class graph path.

### 4.3 Missing semantic edge through the composition/runtime handoff

For the relevant modules, semantic overlay edges exist for worker lifecycle authority and runtime execution, but there are no semantic edges from:

- mission composition / `plan_compiler`
- persisted task-graph metadata/materialization
- runtime dependency keys/input bindings
- task instances/artifacts
- worker dependency gating

as one typed dataflow chain.

Static imports can connect these modules indirectly, but import reachability is not the same as runtime artifact-flow causality.

**Independent evaluation:** the graph-schema-gap portion of the prior diagnosis is confirmed, but should be stated precisely as a **missing first-class semantic/runtime representation**, not as proof the graph is useless for the diagnosis.

---

## 5. Independent graph-native scope of the incident

Using the canonical graph's own traversal semantics—consumer → dependency, reverse traversal for affected consumers, forward traversal for prerequisites—this evaluator seeded only five core source files whose responsibilities are directly implicated by the runtime symptom:

1. `backend/services/mission_composition/job_catalog.py`
2. `backend/services/mission_composition/plan_compiler.py`
3. `backend/services/mission_composition/artifact_schemas.py`
4. `backend/services/tools/mission_input_binding.py`
5. `backend/services/worker_runtime_service.py`

These five files map to 19 graph nodes because the mission-composition files also have function nodes.

The resulting graph-native scope is:

- **120 upstream production consumers**
- **194 downstream production prerequisites**
- **95 impacted tests**
- **2 affected semantic nodes** (`runtime:api`, `runtime:worker`)
- **20 semantic prerequisite nodes**
- multiple architecture invariants in context

This is strong evidence against a producer-only mental model. Even before reading function bodies, the canonical graph says the implicated contracts sit on a broad composition/runtime surface.

This is not evidence that all 120/194 nodes must change. It is blast-radius/review scope, not implementation scope.

---

## 6. Centrality and consumer reach of relevant modules

The graph completeness artifact supplies centrality/reach metrics.

Selected relevant modules:

| Module | Direct consumers | Direct deps | Transitive consumers | Transitive deps | Betweenness |
|---|---:|---:|---:|---:|---:|
| `domain.execution_task` | 28 | 3 | 195 | 4 | 0.00018790 |
| `mission_composition.job_catalog` | 10 | 1 | 136 | 2 | 0.00009995 |
| `mission_composition.artifact_schemas` | 7 | 2 | 102 | 3 | 0.00014841 |
| `tools.mission_input_binding` | 3 | 4 | 72 | 13 | 0.00039743 |
| `mission_composition.plan_compiler` | 9 | 5 | 54 | 159 | 0.00275580 |
| `worker_runtime_service` | 4 | 22 | 6 | 184 | 0.00031128 |
| `tools.knowledge_actions` | 2 | 17 | 166 | 154 | 0.00426630 |
| `mission_composition.revops_deliverable` | 22 | 11 | 57 | 176 | 0.00636529 |

The numbers reinforce that this incident touches high-reuse contracts. In particular, changing `ExecutionTask`, the job catalog, artifact schemas, or knowledge action semantics has a substantial consumer surface.

Again, centrality is not a defect score. It is change-risk context.

---

## 7. Claim-by-claim independent evaluation

### Claim 1 — typed dependency semantics are discarded

**Evaluation: CONFIRMED, but incomplete. The actual mechanism is broader.**

#### 7.1 Contract layer

`JobDependency` supports:

- `hard`
- `conditional`
- `optional`

and explicitly describes itself as a typed dependency rather than unconditional pipeline expansion.

`BusinessJob` carries typed `dependencies`.

#### 7.2 Dependency expansion layer actually honors `optional`

`capability_resolver._dependency_should_expand()` contains explicit behavior:

- optional → do not expand;
- hard → expand;
- conditional → evaluate `satisfied_by` / `required_when_missing`.

Therefore the system does **not** discard dependency type at every stage.

#### 7.3 New independently identified contributing condition: same-outcome co-selection

The catalog declares both:

- `intelligence.retrieve_knowledge`
- `intelligence.advise_next`

as supporting the canonical outcome `observe_contacts`.

`route_jobs_for_intent()` initially selects every business job whose `supported_outcomes` intersects the requested outcomes **before** dependency expansion.

Therefore, if `observe_contacts` is requested, the knowledge job can be selected independently even though the `advise_next → retrieve_knowledge` dependency is optional.

This means optional dependency expansion can be correct while the optional job is already present because of outcome routing.

This contributing condition was not stated in the earlier evaluator's diagnosis.

#### 7.4 A second optionality system also exists

RevOps know-how defines the entire `decision_support` stage:

- jobs: `intelligence.retrieve_knowledge`, `intelligence.advise_next`
- `optional=True`

A repository code search finds no consumer of `stage.optional` / `.optional` semantics that propagates this stage optionality into runtime task-edge behavior.

Thus there are at least **two optionality representations**:

1. `JobDependency.kind="optional"`
2. `KnowHowStage.optional=True`

Neither is present in the final runtime task-edge contract.

#### 7.5 Plan compiler loses dependency type

Once both jobs are selected, `_resolved_dependency_job_keys()` includes selected typed dependencies without branching on `dep.kind`.

`PlannedStepPreview.depends_on` stores only step keys.

`compile_task_graph_preview()` emits generic:

```json
{"dependency_type": "depends_on"}
```

for every edge.

No field survives for hard/conditional/optional semantics or predicates.

#### 7.6 Existing tests ratify the generic-edge behavior

`test_plan_compiler_builds_non_linear_dependency_edges()` explicitly asserts:

```python
for edge in graph["edges"]:
    assert edge["dependency_type"] == "depends_on"
```

A repository search finds no test that instantiates/asserts `kind="optional"` in the test suite.

#### 7.7 Independent conclusion

The prior evaluator was directionally correct but understated the architecture defect.

A fuller mechanism is:

```text
canonical outcome routing
    → optional-stage knowledge job may be selected as a primary job
    → typed JobDependency exists
    → selected typed dependencies collapse to untyped step keys
    → emitted runtime graph carries generic depends_on
    → runtime cannot distinguish optional from hard
```

This is a cross-contract composition defect, not merely one helper function ignoring an enum.

---

### Claim 2 — failed dependencies are classified as merely pending

**Evaluation: CONFIRMED.**

`pending_dependency_keys()` treats an upstream dependency as ready only when its status is exactly `completed`.

The following are therefore semantically collapsed into the same pending result:

- missing task;
- planned/queued;
- claimed/running;
- failed;
- blocked;
- cancelled;
- dead-lettered.

`WorkerRuntimeService.claim_next_task()` then:

1. claims a descendant;
2. calls `pending_dependency_keys()`;
3. if any key is returned, releases the worker lease;
4. transitions the descendant back to `queued`;
5. records dependency deferral metadata;
6. releases the queue lease.

There is no branch in this path for terminally impossible prerequisites.

#### 7.8 Mission rollup interaction

`_maybe_rollup_mission_status()` returns without terminalizing the mission whenever any sibling remains nonterminal.

Therefore a descendant that is continually requeued because an upstream task is permanently failed prevents all-tasks-terminal rollup.

This matches the source-reported mission symptom.

#### 7.9 Existing tests leave the exact hole open

`test_mission_input_binding.py` tests:

- queued dependency → pending;
- running dependency → `DependencyNotReadyError`;
- completed dependency → bind.

A repository search finds no `ExecutionTaskState.FAILED` case in that test file.

`test_mission_status_rollup.py` explicitly proves that a queued sibling keeps a mission `running`, but does not cover causal terminalization of a queued descendant whose hard prerequisite has already failed.

#### 7.10 Independent conclusion

This is not just observability noise. It is a state-machine/edge-semantics defect with an actual liveness consequence.

The repair should distinguish at least:

- hard + terminal failed prerequisite → descendant terminal `blocked`/`cancelled` with causal provenance;
- optional + terminal failed prerequisite → descendant may execute without that artifact;
- conditional → evaluate predicate/availability semantics;
- nonterminal prerequisite → ordinary defer.

Exact target state names remain an implementation decision; this review does not preselect them beyond requiring eventual terminal convergence.

---

### Claim 3 — completed artifact does not mean viable artifact

**Evaluation: CONFIRMED, with an important architectural nuance.**

#### 7.11 Structural validator is intentionally structural

`validate_artifact_payload()`:

- validates list-vs-object shape;
- validates required fields only for items that exist;
- does not impose minimum cardinality;
- does not require nonempty strings/lists;
- does not validate identity/reality/provenance predicates.

The test suite explicitly codifies this design:

```python
assert validate_artifact_payload(PROSPECT_CANDIDATES_SCHEMA, []) == ()
```

and also accepts a structurally complete prospect row with:

```python
"product_description": ""
```

Therefore empty/semantically weak output passing structural validation is not an accidental lack of tests; it is currently an asserted contract.

#### 7.12 Worker completion uses that structural contract

`WorkerRuntimeService.complete()` calls `_validate_declared_output_contract()` before transitioning a task to `COMPLETED`.

That validator uses `validate_artifact_payload()`.

Thus task completion proves the declared artifact exists in the result and satisfies the structural schema. It does **not** prove downstream viability.

#### 7.13 Deliverable completion is deliberately separate

`deliverable_completion.py` explicitly states:

> A task may be completed while its requested deliverable remains incomplete.

Its descriptive completion layer requires actual values for requested typed fields and treats empty artifacts as not satisfying a requested field.

So the final deliverable subsystem is already designed to remain truthful even when a task is structurally complete but semantically insufficient.

#### 7.14 The real mismatch is between task completion and edge viability

`mission_input_binding.apply_input_bindings()` can later reject the same world-state when `binding_required` and no upstream prospects are available.

Therefore the defect is not simply "artifact schema should reject every empty list." It is more precisely:

> task-output structural validity is currently used as a completion criterion without a separately represented edge/downstream viability contract.

A producer may be legitimately complete with zero results for some missions. A downstream job may nevertheless require one or more verified entities. Those are different semantics and should not be collapsed.

#### 7.15 Independent conclusion

The repair should introduce explicit downstream/edge viability predicates or equivalent typed completion conditions, such as:

- minimum cardinality when the downstream job requires an entity set;
- identity/reality predicate;
- required evidence/provenance predicate;
- contact predicate;
- artifact-specific qualification predicate.

Whether those predicates live in artifact schemas, edge contracts, job input contracts, or a separate viability layer should be decided after architecture review. The evidence argues for the semantic capability, not one predetermined storage location.

---

### Claim 4 — knowledge retrieval has an unresolved contract mismatch

**Evaluation: CONTRACT MISMATCH CONFIRMED; runtime failure cause remains UNRESOLVED.**

#### 7.16 Job catalog contract

`intelligence.retrieve_knowledge` declares:

- `required_inputs=("observed_contacts",)`
- hard dependency on `research.observe_sources`
- action `knowledge.retrieve_current`

#### 7.17 Plan compiler behavior

`_binding_input_path()` explicitly returns `None` for `knowledge.retrieve_current`.

Therefore the observed-contacts dependency can create ordering but no artifact input binding.

#### 7.18 Action input contract makes the mismatch more concrete

`knowledge_actions.RetrieveCurrentKnowledgeInput` contains:

```python
query: KnowledgeRetrievalQuery
```

There is no `observed_contacts` field in that action input model.

Thus the business-job declaration says observed contacts are required, while the selected action contract has no direct representation for that required artifact.

This is a real declarative/runtime contract incoherence.

#### 7.19 What is not proven

The exact source-reported `knowledge.retrieve_current` task failed, but this independent evaluator does not possess its audit row or exception trace.

The task could have failed because of:

- malformed/generated query;
- missing runtime session/context;
- data-state problem;
- knowledge retrieval error;
- unrelated handler failure;
- some consequence of the contract mismatch.

The static mismatch cannot be substituted for the missing runtime exception.

#### 7.20 Test gap

Repository code search finds no test reference to:

- `intelligence.retrieve_knowledge`
- `knowledge.retrieve_current`

in the test corpus at the frozen boundary.

This is relevant because the graph can point at `knowledge_actions.py`, but there is no mission-composition integration proof specifically exercising this business-job/action binding.

---

### Claim 5 — the graph product cannot represent this diagnosis directly

**Evaluation: CONFIRMED in a narrower, artifact-backed sense.**

The exact graph artifact proves:

1. first-class node vocabulary lacks mission jobs, runtime task instances, artifact instances, edge predicates, failure causes, and blocking chains;
2. function-level representation is confined to `mission_composition`;
3. the semantic overlay does not model the composition → materialization → runtime dependency/artifact-flow handoff;
4. none of the 16 frozen architecture invariants govern:
   - typed mission dependency preservation;
   - optional/conditional edge execution semantics;
   - artifact viability/cardinality;
   - failed-prerequisite descendant terminalization;
   - task failure causal propagation.

The graph can still:

- identify source neighborhoods;
- reveal high-centrality/reuse contracts;
- select related tests;
- expose broad blast radius;
- connect the incident to worker/runtime and other architecture surfaces.

It cannot currently produce the runtime causal statement directly from graph-native entities.

Therefore the best-supported conclusion is:

> The canonical graph is useful as a repository architecture/change-impact instrument for this incident, but its current schema is insufficient for first-class runtime mission/artifact/edge-causality diagnosis.

That supports evaluating a Graph+ extension. It does not imply the canonical repository graph should be discarded or indiscriminately expanded.

---

## 8. Independent graph finding the earlier evaluator did not identify: proof can select the right tests and still miss the invariant

This incident exposes a limitation in proof selection that is distinct from simple test coverage.

The graph maps the relevant modules to tests correctly. However several selected/direct tests encode the deficient behavior as expected behavior:

### 8.1 Generic dependency edges

The composition test asserts all graph edges have:

```text
dependency_type == "depends_on"
```

That test does not merely fail to catch loss of optionality; it positively ratifies the current generic representation.

### 8.2 Empty artifact acceptance

The artifact-schema test explicitly asserts an empty prospect list is valid and accepts blank `product_description` when the field exists.

Again, this is not missing test reachability. It is missing semantic distinction between structural validity and edge viability.

### 8.3 Failed dependency case absent

The input-binding test reaches the right module but covers queued/running/completed states, not failed/blocked/dead-lettered upstream dependencies.

### 8.4 Implication for graph-assisted proof

A dependency graph can select tests based on reachability, but it cannot determine that the tests encode an insufficient invariant unless the invariant itself is represented and checked.

This suggests a Graph+ capability opportunity:

```text
change / runtime incident
    → graph scope
    → applicable semantic invariant
    → required behavioral predicate
    → tests proving that predicate
```

rather than only:

```text
change
    → graph scope
    → tests that reference affected code
```

This is potentially important to the study because it distinguishes **test selection quality** from **proof obligation quality**.

---

## 9. Independent finding: optionality is represented in three places but not reconciled

The incident reveals at least three related semantic layers:

1. `KnowHowStage.optional`
2. `JobDependency.kind`
3. runtime graph edge `dependency_type`

At the frozen boundary:

- know-how marks `decision_support` optional;
- business job dependency marks `advise_next → retrieve_knowledge` optional;
- runtime graph emits generic `depends_on` only.

There is no first-class reconciliation check stating that optionality must remain semantically consistent across these layers.

This is a stronger architecture observation than "one enum is dropped." It is a **cross-representation semantic drift** problem.

A future graph/invariant layer could potentially detect this automatically if job/stage/task-edge entities become first class.

---

## 10. Independent finding: the frozen graph itself does not contain the mission-level data needed to reproduce the runtime failure

Even with the exact artifact, this evaluator cannot query:

- mission `4fb6743c-eb06-4f06-bc94-49ae72e576e2`;
- its seven materialized task nodes;
- exact task dependency kinds/keys as runtime instances;
- exact artifact payload lineage;
- the failed knowledge task's exception;
- the failed lead-enrichment task's bound input;
- causal ancestry of queued descendants.

Those facts exist, if at all, in the runtime database/audit/evidence/lineage state rather than in the canonical repository graph artifact.

This is precisely the boundary between:

- **repository architecture graph**, and
- **live mission-state/causal graph overlay**.

The incident supplies a concrete use case for evaluating whether those should be connected.

---

## 11. What the graph independently contributes to the diagnosis

The graph's contribution can now be evaluated more precisely.

### 11.1 Positive contribution supported by independent reproduction

The exact graph independently supports:

- rejecting a producer-only scope assumption;
- identifying the composition/runtime contracts as broad-impact surfaces;
- locating the relevant module neighborhoods;
- identifying direct/indirect test populations;
- showing that graph function precision ends at the mission-composition boundary;
- showing that mission-job/artifact/task/failure entities are absent;
- showing there is no applicable frozen invariant for typed mission dependencies or artifact viability.

### 11.2 What required source inspection

The graph artifact alone does **not** prove:

- `_resolved_dependency_job_keys()` ignores dependency kind;
- outcome co-selection selects knowledge independently;
- the worker requeue loop behavior;
- empty list acceptance;
- blank product-description acceptance;
- exact action input mismatch;
- exact runtime task exception.

Those mechanisms required reading the source/tests selected or contextualized by the graph.

### 11.3 Attribution control

Therefore statements such as "the graph located the architectural causes" are too strong unless contemporaneous graph-query logs demonstrate that sequence.

The independently supportable statement is:

> The graph supplied a broad and relevant architectural scope; source/test inspection within that scope established the concrete mechanisms.

That is still a meaningful graph contribution, but a different one.

---

## 12. Revised independent root-cause model

The evidence currently supports a multi-layer mechanism:

```text
RevOps intent / observe-contact outcome
        |
        v
job routing
  - multiple jobs share observe_contacts
  - optional decision-support jobs can therefore enter selection directly
        |
        v
know-how + job dependency semantics
  - decision_support stage is optional
  - advise_next → retrieve_knowledge is optional
        |
        v
plan compiler
  - selected typed dependency becomes untyped step key
  - graph edge becomes generic depends_on
  - knowledge required observed_contacts has no artifact binding
        |
        v
runtime task graph
  - dependency key has no typed execution semantics
        |
        v
worker readiness
  - only completed counts as ready
  - terminal failure and temporary incompleteness collapse to pending
        |
        v
descendant claim/defer/requeue loop
  - impossible descendants remain open
        |
        v
mission rollup
  - open descendants prevent terminal rollup
```

Separately:

```text
producer task completes
        |
        v
structural artifact validation
  - empty collection allowed
  - nonempty-field semantics not required
        |
        v
task = completed
        |
        +--> deliverable read model may truthfully remain incomplete
        |
        v
downstream binding
  - binding_required may reject empty world-state
        |
        v
downstream failure / no viable artifact
```

These two chains intersect but should not be collapsed into one cause.

---

## 13. Implications for the proposed Ajenda repair

This review does not prescribe an exact patch, but a complete repair should demonstrate that it has considered all independently supported boundaries:

### 13.1 Dependency semantics

- preserve dependency kind through composition, plan, materialized graph, and runtime;
- reconcile know-how-stage optionality with job dependency optionality;
- prevent same-outcome routing from silently defeating optional semantics;
- define conditional predicate transport/evaluation if conditional edges enter runtime.

### 13.2 Terminal propagation

- distinguish temporary not-ready from terminally impossible upstream states;
- make impossible hard descendants terminal with causal provenance;
- ensure mission rollup converges;
- ensure optional failure does not block otherwise viable work.

### 13.3 Artifact viability

- keep structural schemas structurally honest;
- add explicit downstream viability/precondition semantics rather than assuming structure equals usefulness;
- represent cardinality/identity/provenance/contact predicates where required;
- keep final deliverable truthfulness independent from task execution status.

### 13.4 Knowledge contract

- reconcile the job's declared `observed_contacts` requirement with the selected action's actual input schema;
- either bind a representable artifact/context, change the declared requirement, or choose a different action/contract;
- recover the specific runtime exception before claiming this mismatch caused the observed knowledge failure.

### 13.5 Observability

- expose task failure reason/code in ordinary task/mission read models or a causally linked diagnostic projection;
- expose which upstream task/artifact caused descendant blockage;
- preserve audit-event authority rather than duplicating unverifiable prose.

---

## 14. Implications for the broader graph product

The runtime incident provides a concrete candidate capability set for Graph+, now derived from the exact graph's limitations rather than from preference.

Potential first-class entities/relationships to evaluate:

- business job nodes;
- registered action/ability nodes;
- know-how stage nodes;
- artifact-contract nodes;
- materialized runtime-task nodes or a live overlay;
- runtime artifact-instance nodes or references;
- typed dependency edges (`hard`, `conditional`, `optional`);
- predicate/precondition relationships;
- produces/consumes/binds edges;
- task-state overlay;
- causal-blocked-by relationships;
- failure-reason/evidence links;
- deliverable-field provenance links.

Potential invariants:

- typed dependency preservation across representations;
- optional-stage consistency;
- every declared required input must be representable by the selected action/binding contract;
- hard failed dependencies terminalize descendants;
- optional failed dependencies do not hard-block descendants;
- artifact viability requirements are explicit where downstream work requires them;
- runtime task failure has retrievable causal provenance.

These are **candidate extensions**, not accepted design requirements. They should be evaluated against complexity, maintainability, false-positive risk, and actual diagnostic value.

---

## 15. Study interpretation

### 15.1 What this incident can support now

It supports the observation that:

- the canonical graph independently broadens the plausible correction scope beyond a local producer;
- the exact graph exposes its own representation boundary;
- source/test inspection inside that graph-selected scope reveals multiple cross-layer semantic mismatches;
- some existing tests encode the weak semantics, so proof-selection reachability alone is insufficient.

### 15.2 What it cannot support yet

It does **not** yet prove:

- graph-assisted repair is better than pre-graph repair;
- graph use will reduce corrective descendants;
- the implementing LLM actually found each mechanism because of the graph;
- Graph+ extensions will improve outcomes;
- the current graph caused any runtime defect;
- the RevOps repair will be complete.

### 15.3 Current independent graph-contribution classification

For this diagnostic phase only, the best classification is:

**mixed-positive diagnostic contribution**

Reason:

- positive: broad scope, architecture neighborhood, test surface, representation gaps;
- limited: concrete causal mechanisms still required code/test inspection;
- negative evidence: no evidence yet that graph guidance caused unnecessary scope or wrong diagnosis;
- unresolved: implementation quality and downstream cascade outcome are not yet observable.

This classification applies to the diagnostic phase only and must not be converted into a treatment-effect conclusion.

---

## 16. Required evidence after the repair PR exists

The later implementation should be evaluated against this independent record.

Capture:

1. implementation PR number/head SHA;
2. exact changed files;
3. contemporaneous graph impact/proof/completeness/decision artifacts;
4. whether job/stage/edge optionality is preserved end-to-end;
5. tests for hard/optional/conditional terminal dependency cases;
6. tests proving downstream viability semantics separately from structural artifact validity;
7. knowledge job/action input reconciliation proof;
8. task failure/read-model causal observability proof;
9. controlled replay of the original mission or equivalent fixture;
10. terminal mission state;
11. final deliverable completion truthfulness;
12. no external-send side effect unless explicitly authorized;
13. later corrective descendants.

A complete evaluation should compare not only whether tests pass but whether the repair closes the semantic boundaries identified here without introducing unrelated expansion.

---

## 17. Bottom line

The independent exact-graph evaluation changes the confidence of several claims.

### Confirmed

- canonical graph at #496 has no first-class mission job/artifact/task/failure causal model;
- function-level graph precision stops at `mission_composition`;
- graph-native scope is much broader than a producer-only correction;
- typed dependency semantics are lost before runtime;
- failed prerequisite and temporary-not-ready states collapse in runtime readiness;
- task completion is structurally weaker than downstream viability;
- knowledge required-input/action-input contracts are inconsistent;
- current proof relationships can select tests that themselves encode insufficient semantics.

### Newly identified in this independent pass

- optional dependency expansion is not the only cause: same-outcome routing can independently select the optional knowledge job;
- RevOps know-how contains a second optionality representation (`KnowHowStage.optional`) that is not reconciled with runtime dependency edges;
- proof-selection quality and proof-obligation quality are separate graph concerns.

### Still unresolved

- exact exception for the failed knowledge task;
- exact runtime-instance dependency metadata for the seven tasks;
- whether the implementing LLM's concrete conclusions were graph-derived or code-derived;
- whether the eventual repair improves corrective-cascade outcomes.

The strongest evidence-bounded conclusion is therefore:

> This runtime incident is both an Ajenda semantic/runtime defect cluster and a concrete demonstration of the current canonical graph's boundary. The graph is already useful for broad architectural scope and proof targeting, but it does not yet model the mission/artifact/dependency causality needed to express this failure end-to-end. Whether extending it produces better repairs remains an open empirical question to be tested by the next PR and replay.
