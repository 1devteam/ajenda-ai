# Graph-Use Provenance and Method Comparison v0.1

**Status:** methodological evidence record; not a treatment-effect finding  
**Repository:** `1devteam/ajenda-ai`  
**Frozen product boundary for independent comparator:** PR #496 head `b8595583c7ece455eae8c452b050b5af708df29d`; merged `main` boundary `9a3a3009217d0ea564bd0a04086330a5bc491db5`  
**Purpose:** explain why the implementing/evaluating LLM and the independent evaluator produced overlapping but non-identical RevOps findings by reconstructing the graph provenance, query method, seeds, investigation order, and graph-vs-source attribution used by each.

---

## 1. Why this record exists

The study now has two materially different diagnostic procedures applied to the same RevOps incident:

1. an implementing/evaluating LLM that was initially given runtime evidence, later instructed to use the graph to scope the issue, and then reported a broader diagnosis; and
2. an independent evaluator that later downloaded the exact successful PR #496 canonical graph artifact and evaluated the incident against that frozen artifact before reading the implicated source/tests.

The two evaluations overlap strongly on several defects but differ in graph counts, scope metrics, several causal mechanisms, and how much credit can defensibly be assigned to graph-native reasoning.

The implementing/evaluating LLM has now supplied a detailed self-report of what it actually did. That self-report is important because it corrects an earlier ambiguity: it did **not** run Ajenda's graph generator or official graph-analysis CLI. It queried a pre-existing local JSON graph artifact with ad hoc `jq` filters and then inspected GitHub source separately.

This record preserves that distinction rather than collapsing both procedures under the label "ran the graph."

---

## 2. Evidence classes and provenance discipline

### 2.1 Source-reported facts from the implementing/evaluating LLM

The following facts are taken from its explicit self-report and are not independently reproducible from this evaluator's environment unless separately noted:

- scratch path of its queried graph;
- scratch-file Git object hashes;
- presence and shape of its second local graph artifact;
- exact `jq` commands it says it executed;
- exact order in which it says hypotheses, graph inspection, and source inspection occurred;
- its description of what it would have repaired before versus after graph-guided source inspection.

These are recorded as **source-reported methodological evidence**, not silently promoted to repository facts.

### 2.2 Independently verified facts

The independent evaluator directly verified:

- PR #496 product head and merged-main boundary;
- successful canonical dependency-graph workflow for the #496 head;
- exact workflow artifact provenance;
- exact canonical graph node/edge counts and schema;
- canonical graph node/edge vocabulary and selective function-layer coverage;
- canonical graph traversal semantics from Ajenda's graph-analysis implementation;
- relevant source/test contracts at the frozen #496 boundary;
- independent transitive scope results from the five directly implicated modules.

### 2.3 No inference of motive

This document evaluates procedure and evidentiary consequences. It does not infer spite, intent, or bad faith from the earlier framing error or later provenance correction.

---

## 3. Side-by-side procedure summary

| Dimension | Implementing/evaluating LLM | Independent evaluator | Consequence |
|---|---|---|---|
| Graph provenance | Unknown scratch artifact; no repo/ref/SHA encoded | Exact PR #496 CI artifact, workflow/run/artifact/digest pinned | Different evidentiary authority |
| Reported graph size | 1,239 nodes / 3,717 edges | 1,265 nodes / 3,818 edges | Not the same graph snapshot |
| Graph generation during diagnosis | No | No new product graph generation; exact CI artifact downloaded | Independent pass uses frozen canonical output |
| Official impact CLI | Not run | Canonical traversal semantics reproduced from frozen graph/implementation | Different scope method |
| Query style | Regex scans, node-type inventories, one-hop incident/incoming edges | Transitive consumer/dependency traversal plus artifact bundle inspection | Independent pass sees larger blast radius |
| Seed basis | Hand-selected module/node strings after runtime symptoms were known | Five directly implicated source files, mapped to 19 graph nodes | Different starting scope |
| PR diff as seed | No | Not used as primary incident seed; frozen PR artifact used for provenance | Neither equates PR diff with runtime incident |
| Mission ID in graph | No | No; canonical graph cannot represent live mission instance | Shared graph limitation |
| Business jobs as graph nodes | No | No | Shared graph limitation |
| Proof selection | Not run/used | Frozen artifact bundle inspected; proof-system limitations independently evaluated | Other LLM cannot claim proof-selection contribution |
| Completeness/architecture decision | Not run/used | Frozen canonical bundle/procedure inspected | Different architecture evidence |
| Runtime hypotheses before graph | Yes | Runtime symptom known, but independent mechanism review deliberately separates graph scope from later source proof | Different contamination risk |
| Source inspection | Major source of concrete root causes | Major source of concrete root causes after graph scope | Both require code for helper-level causality |
| Graph-native causal diagnosis | Limited | Limited by graph schema/function coverage | Shared current product boundary |

---

## 4. Exact graph provenance divergence

### 4.1 Implementing/evaluating LLM graph

The LLM reports that its primary queried artifact was:

```text
dependency-graph.v1.json
/workspace/scratch/c567b5977855/graph-main/docs/architecture/dependency-graph.v1.json
```

Source-reported local Git-object hash:

```text
0a775adbbb1bdb2424dd9977024d0b1752f2a72c
```

Reported contents:

- schema 1.2;
- 1,239 nodes;
- 3,717 edges;
- no repository encoded;
- no ref encoded;
- no commit SHA encoded;
- no generation timestamp encoded;
- `generated_from` only described static source globs, semantic overlay, and selective function layer.

The LLM explicitly states:

- the graph was pre-existing in scratch space;
- it was not generated during the diagnosis;
- there was no local Ajenda repository checkout in that workspace;
- no commit association was established.

It separately inspected GitHub `main` and later confirmed `main` as `9a3a3009217d0ea564bd0a04086330a5bc491db5`, but correctly acknowledges that this does **not** prove its scratch graph came from that SHA.

It also reports a second local artifact with 1,235 nodes / 3,698 edges, which was not the graph used for the main diagnostic queries.

### 4.2 Independent canonical graph

The independent evaluator used the exact successful PR #496 graph artifact:

- workflow: `Architecture — Canonical Dependency Graph`;
- workflow run: `33299501967`;
- PR #496 head: `b8595583c7ece455eae8c452b050b5af708df29d`;
- artifact: `canonical-dependency-graph`;
- artifact id: `9728467919`;
- artifact digest: `sha256:c4d4b7b407523628c02bda9423c3e36b3fee03c75586d556210d6acd0330b206`;
- schema 1.2;
- 1,265 nodes;
- 3,818 edges.

### 4.3 Interpretation of the count difference

Observed difference relative to the primary scratch artifact:

- +26 nodes in the frozen canonical graph;
- +101 edges in the frozen canonical graph.

This difference alone does **not** explain every diagnostic difference. It establishes only that the two evaluators did not operate on provenance-equivalent graph snapshots.

Potential explanations for the scratch artifact include:

- earlier/later commit;
- another branch;
- another local generation state;
- different generation mode/input state;
- stale extracted artifact.

The implementing/evaluating LLM does not know which explanation applies. Therefore the scratch graph cannot be treated as the canonical #496 graph for study attribution.

---

## 5. Query-method divergence

### 5.1 Implementing/evaluating LLM method

The LLM reports **no execution** of:

- graph build;
- official impact analysis;
- proof selection;
- completeness generation;
- architecture-decision generation;
- selective-CI graph operation.

Its graph operations were ad hoc `jq` inspection of the JSON artifact.

Reported operations included:

1. artifact discovery with `find`;
2. graph metadata/key inspection;
3. schema samples;
4. regex full-node scans;
5. one-hop incident-edge queries against selected node IDs;
6. node/edge-type inventories;
7. regex action/artifact string scans;
8. invariant and semantic-finding regex scans;
9. direct incoming-consumer/test queries;
10. local file hash/provenance checks.

The core incident-edge query was explicitly:

- both directions;
- one edge deep;
- no recursive/transitive traversal.

The direct-consumer query was:

- incoming edges only;
- one edge deep.

### 5.2 Independent evaluator method

The independent pass:

1. pinned the exact successful PR #496 canonical workflow artifact;
2. inspected the graph artifact and bundled impact/proof/completeness/architecture outputs;
3. inspected graph generation scope and vocabulary;
4. used Ajenda's canonical consumer→dependency direction and impact-traversal semantics;
5. seeded five directly implicated source files;
6. traversed transitive upstream consumers and downstream prerequisites;
7. derived the impacted-test population;
8. inspected graph invariants/semantic boundaries;
9. then inspected source/tests to determine concrete mechanisms.

The resulting graph-native scope from the five source seeds was:

- 19 mapped start graph nodes;
- 120 upstream production consumers;
- 194 downstream prerequisites;
- 95 impacted tests.

### 5.3 Why this difference matters

One-hop neighborhood lookup and transitive architectural impact analysis answer different questions.

The first answers roughly:

> What directly references or is referenced by these selected nodes?

The second answers:

> What production consumers can be affected transitively, what prerequisites does the implicated surface depend upon, and which tests are connected to the affected production closure?

Therefore the larger independent blast-radius result is not evidence that one evaluator simply "looked harder" at the same output. It follows from a materially different traversal procedure.

---

## 6. Seed-selection divergence

### 6.1 Other LLM seeds

The implementing/evaluating LLM reports selecting specific node IDs and regex strings, including modules for:

- knowledge actions;
- GTM actions;
- mission input binding;
- worker runtime;
- dispatcher;
- worker loop;
- execution-task repository;
- plan compiler;
- deliverable runtime/read model;
- deliverable completion.

It also performed regex searches for artifact/action strings such as:

- `retrieved_knowledge`;
- `enriched_prospects`;
- `qualified_prospects`;
- `prospect_candidates`;
- `introduction_drafts`;
- `retrieve_current`;
- `lead_enrich`;
- `recommend_next`;
- `email_draft`.

These seeds were chosen after runtime symptoms and some hypotheses were already known.

No business-job IDs, PR diff, changed-file set, or mission ID were passed into an official graph traversal.

### 6.2 Independent seeds

The independent pass used five responsibility-bearing source files directly implicated by the runtime symptom:

1. `backend/services/mission_composition/job_catalog.py`
2. `backend/services/mission_composition/plan_compiler.py`
3. `backend/services/mission_composition/artifact_schemas.py`
4. `backend/services/tools/mission_input_binding.py`
5. `backend/services/worker_runtime_service.py`

These mapped to 19 nodes because mission-composition files also have function nodes.

### 6.3 Interpretation

The implementing/evaluating LLM's seed selection was **hypothesis-directed**. The independent seeds were **responsibility-surface-directed** and then expanded transitively.

Neither is inherently invalid. They have different bias profiles:

- hypothesis-directed seeds are efficient but can miss alternative causal neighborhoods;
- responsibility-surface seeds are broader but can generate large review scope requiring disciplined narrowing.

This is a plausible contributor to why the independent pass found cross-representation optionality and proof-obligation issues that were absent from the earlier diagnosis.

However, those new mechanisms were ultimately established from source/test inspection, so the study must not attribute them solely to the larger graph snapshot or transitive traversal.

---

## 7. Investigation-order divergence

### 7.1 Implementing/evaluating LLM sequence

Its self-reported sequence was:

1. read supplied runtime mission state;
2. carry forward hypotheses about:
   - unverified research candidates;
   - failed upstream dependencies;
   - stuck queued descendants;
   - missing failure reason on task records;
3. load prior context about intended graph scope;
4. discover local graph artifacts;
5. inspect graph schema/structure;
6. query graph neighborhoods;
7. inspect GitHub source for graph-selected modules;
8. inspect relevant tests;
9. inspect graph invariants/semantic findings/direct consumers;
10. confirm GitHub `main` SHA separately;
11. form expanded repair scope.

It explicitly acknowledges:

> The hypotheses about failure propagation and producer quality existed before querying the graph.

and:

> The graph did not independently generate the hypotheses.

### 7.2 Independent sequence

The independent pass was designed to separate evidence classes:

1. preserve runtime observations as source-reported;
2. pin exact canonical graph provenance;
3. establish graph-native schema, coverage, and scope;
4. traverse the implicated responsibility surface;
5. inspect selected/relevant tests;
6. inspect source mechanisms;
7. classify each conclusion as graph-native, graph-guided/source-derived, runtime-derived, or unresolved.

### 7.3 Consequence for causal attribution

The other LLM's later broader diagnosis cannot be interpreted as:

> graph generated a broader hypothesis set from scratch.

Its own account supports the narrower statement:

> runtime evidence generated initial hypotheses; graph inspection helped select and contextualize a source/test neighborhood; source inspection established the concrete cross-layer mechanisms.

This is still graph-assisted reasoning, but at a lower and more specific contribution level.

---

## 8. Finding-attribution comparison

| Finding | Other LLM's own attribution | Independent attribution | Current adjudication |
|---|---|---|---|
| Unverified research candidates | Runtime evidence | Runtime evidence | Runtime-derived |
| Two upstream failures + queued descendants | Runtime evidence | Runtime evidence | Runtime-derived |
| Typed dependency semantics lost before runtime | Runtime symptom + graph led to modules + source | Graph scope + source | Source-established, graph-guided |
| Every compiled edge generic `depends_on` | Source | Source/test | Source-established |
| Failed prerequisite treated as pending | Runtime symptom + graph led to modules + source | Graph scope + source/test | Source-established, graph-guided |
| Requeue/liveness loop | Source + runtime | Source + runtime | Combination |
| Empty structural artifact accepted | Source | Source/test | Source-established |
| Downstream empty-world rejection | Runtime + source | Runtime + source/test | Combination |
| Knowledge required-input/action mismatch | Source | Source | Source-established |
| Exact failed knowledge exception | Not determined | Not determined | Unresolved |
| Failure reason absent from `ExecutionTask` | Runtime + source | Source | Source-established |
| Failure reason persisted in audit | Source | Source | Source-established |
| Missing optional-failure test | Graph located tests + test reading | Graph scope + test reading | Graph-guided/test-established |
| Missing mission/artifact/task/failure graph entities | Graph | Exact canonical graph | Graph-native; independently confirmed |
| Selective function-layer boundary | Graph `generated_from` | Exact canonical graph | Graph-native; independently confirmed |
| Missing relevant runtime invariants | Graph invariant scan | Exact canonical graph | Graph-native; independently confirmed |
| Same-outcome co-selection of knowledge job | Not identified | Source after graph scope | New independent source finding |
| `KnowHowStage.optional` not reconciled to runtime edges | Not identified | Source/search after graph scope | New independent source finding |
| Test selection can reach tests that encode weak semantics | Not identified | Exact graph + tests | New independent graph/proof observation |

---

## 9. What specifically explains the different findings

The available evidence supports at least five nonexclusive explanations.

### 9.1 Different graph snapshot

The two graph artifacts have different node/edge counts and only the independent artifact has frozen PR #496 provenance.

This can alter:

- available nodes;
- available edges;
- test relationships;
- semantic findings;
- function-layer contents;
- reachability metrics.

It cannot yet be quantified as the cause of any specific missed finding because the scratch artifact's generating commit is unknown.

### 9.2 Different traversal depth

The other LLM used one-hop and regex inspection. The independent pass used transitive architecture-impact semantics.

This directly explains why the independent pass could quantify broad system scope while the other LLM could only report direct neighborhoods.

### 9.3 Different seed strategy

The other LLM selected nodes based on already-formed hypotheses. The independent pass started from responsibility-bearing files and expanded systematically.

This can affect what alternative architecture paths become visible.

### 9.4 Different graph/source boundary discipline

The other LLM's earlier narrative blurred graph-guided source findings with graph-native findings. Its new self-report corrects that and explicitly says:

> None of the major runtime root causes came directly from a graph-native architecture finding.

The independent pass explicitly separated those categories from the beginning.

This difference affects **credit assignment**, even where both evaluators eventually find the same bug.

### 9.5 Different source/test inspection depth

The independent pass found additional mechanisms—same-outcome routing, stage optionality, and proof-obligation weakness—only after reading deeper contracts/tests.

Those differences cannot be attributed solely to canonical-versus-scratch graph provenance. They may reflect inspection depth, search strategy, or reasoning differences after the graph step.

---

## 10. Revised classification of the implementing/evaluating LLM's graph exposure

A binary label such as `graph_used=true` is too coarse for this incident.

The self-report supports the following exposure vector:

| Capability | Other LLM use during diagnosis |
|---|---|
| Verified canonical graph provenance | No |
| Graph generated from known target SHA | No |
| Official graph impact command | No |
| Transitive architecture traversal | No |
| One-hop graph neighborhood inspection | Yes |
| Graph node/edge vocabulary inspection | Yes |
| Invariant inventory inspection | Yes, regex search only |
| Semantic-finding inspection | Yes, regex search only |
| Proof selection | No |
| Completeness analysis | Not materially used |
| Architecture decision | No |
| Function-level graph inspection where available | Yes |
| Graph-guided source localization | Yes |
| Graph-native runtime mission causality | Impossible with current graph and not performed |
| Live mission graph/runtime overlay | No |
| Source/test follow-through | Yes |

A defensible working label is:

> **partial graph-assisted diagnosis: unprovenanced artifact inspection + graph-guided source localization**

This is not equivalent to:

> **canonical graph pipeline execution**

and not equivalent to:

> **graph-native causal diagnosis**.

This distinction should be preserved in later treatment-intensity analyses.

---

## 11. Revision to graph-contribution credit for that LLM

Before receiving the self-report, it was possible to interpret its broader diagnosis as evidence that running the graph itself exposed several architectural causes.

The self-report requires narrower attribution.

### Direct graph contribution supported by its own account

Its scratch graph directly contributed:

- module/test neighborhood localization;
- worker/runtime architecture context;
- visibility of graph representation gaps;
- visibility that no suitable invariant was present in that artifact.

### Graph-guided but source-established contribution

The following were found after graph-guided source inspection:

- dependency-kind loss;
- generic runtime edges;
- failed-dependency defer/requeue semantics;
- empty artifact structural semantics;
- knowledge input mismatch;
- task/audit observability split;
- missing tests for terminal dependency cases.

### No demonstrated graph contribution

The graph did not directly generate:

- the original producer-quality hypothesis;
- the original failed-dependency hypothesis;
- the runtime observation that tasks were stuck;
- the concrete failed knowledge-task exception;
- proof selection;
- architecture-decision output;
- live mission causal reconstruction.

### Working diagnostic-phase classification

For the implementing/evaluating LLM specifically, a more precise classification is:

**limited-positive / partial graph-assisted contribution**

because the graph helped broaden/localize source inspection and expose graph-schema gaps, while most causal mechanisms came from runtime evidence and source/test reading.

This classification is not a judgment about the canonical graph product's capability. It characterizes the procedure actually performed by that LLM.

The independent canonical-graph pass remains separately classified as **mixed-positive diagnostic contribution**, because exact provenance and transitive architecture scope were independently reproduced while helper-level causality still required source inspection.

---

## 12. Implication for the earlier evaluator-framing concern

The earlier unsolicited statement that the incident was "not a graph-tool problem" occurred before a complete graph investigation.

The new self-report establishes an important methodological sequence:

- the initial framing preceded graph inspection;
- later graph use was prompted;
- that graph use relied on an unprovenanced scratch artifact;
- the eventual broad root-cause diagnosis was mainly source-derived after graph-guided localization.

This strengthens the classification of the original statement as a **premature evaluator statement** rather than an evidence-based graph conclusion.

It does **not** establish spite or intentional bias.

The appropriate scientific control remains:

- preserve the statement chronologically;
- preserve the minimal later instruction;
- preserve exactly what graph procedure followed;
- evaluate the implementation outcome independently;
- do not compensate by favoring a graph-positive interpretation.

---

## 13. Implication for the study's treatment variable

The incident demonstrates that "graph-assisted" is not binary.

Future coding should preserve a capability/intensity vector such as:

1. graph provenance verified;
2. graph matches target commit;
3. canonical generator/build executed or exact canonical artifact used;
4. official or semantically equivalent impact traversal used;
5. transitive blast radius inspected;
6. invariants inspected;
7. proof obligations selected;
8. completeness/architecture decision inspected;
9. graph-selected source/tests read;
10. graph limitations explicitly recorded;
11. live runtime overlay/mission causality available;
12. implementation changed because of graph evidence.

This vector must be defined and applied consistently. It should not be tuned after seeing which procedure produced the better repair.

The current incident can then be coded as different exposure profiles rather than falsely treating both evaluators as receiving the same graph treatment.

---

## 14. New prospective comparison opportunity

The implementing/evaluating LLM supplied a rare before/after statement of proposed repair scope.

### Before its graph inspection

It reports that runtime evidence alone would have led it toward:

- prospect verification/classification;
- failure-reason observability;
- stuck downstream dependency handling;
- possibly empty prospect binding.

### After graph-guided source inspection

It reports a broader proposed repair scope:

- preserve dependency kinds through composition/materialization/runtime;
- terminally propagate failed hard dependencies;
- allow optional-dependency failure without blocking;
- evaluate conditional dependencies against predicates/availability;
- add artifact viability/cardinality semantics;
- improve correlated failure read models;
- reconcile knowledge job/input contracts;
- extend graph representation with runtime semantic/causal concepts.

This is potentially valuable within-case evidence that the investigation broadened after graph-guided inspection.

However, causal attribution is confounded because the broader scope followed **both graph inspection and deeper source inspection**. The study should not attribute the entire expansion to the graph.

A better decomposition is:

- **runtime evidence contribution:** supplied symptoms and initial hypotheses;
- **graph contribution:** localized/broadened architecture neighborhood and exposed representation gaps;
- **source contribution:** established specific implementation mechanisms;
- **reasoning contribution:** synthesized those mechanisms into a larger repair plan.

---

## 15. Predictions that can now be tested without further coaching

Because the other LLM has already stated its intended broad repair scope, later implementation can be compared against this contemporaneous record.

### Prediction A — if the broad diagnosis is actually operationalized

The implementation should address more than producer filtering. It should contain evidence for multiple contract boundaries, potentially including dependency semantics, terminal convergence, artifact viability, knowledge coherence, and observability.

### Prediction B — if the diagnosis remains mostly rhetorical

The implementation may collapse back toward a narrow local producer/binding patch despite the broader written diagnosis.

### Prediction C — if the broader scope is over-expansion

The implementation may touch unnecessary architecture, increase complexity, or generate corrective descendants unrelated to the original runtime deficiency.

### Prediction D — if graph limitations materially matter

The repair may succeed but still require code-first reconstruction because the current graph lacks runtime mission/artifact causality.

### Prediction E — if graph-informed scope improves proof quality

The PR should contain behavioral tests for semantic obligations—not merely tests located by dependency reachability—including hard/optional/conditional terminal behavior and structural-vs-viability distinctions.

None of these predictions is a preferred outcome.

---

## 16. What this comparison does not establish

It does not establish that:

- the other LLM intentionally misrepresented its graph work;
- the scratch graph was defective;
- the 26-node/101-edge difference caused a specific missed finding;
- canonical graph use automatically produces deeper reasoning;
- transitive traversal is always superior to focused one-hop inspection;
- the independent evaluator's broader diagnosis is necessarily the better repair plan;
- Graph+ extensions will reduce corrective cascades;
- the eventual repair will succeed.

It establishes a methodological fact:

> the two evaluations were performed under materially different graph provenance, traversal depth, seed strategy, investigation order, and graph/source attribution discipline.

That fact must be accounted for before comparing diagnostic quality.

---

## 17. Most important study-level interpretation

The observed difference should not be summarized as:

> "LLM A used the graph badly and LLM B used it well."

That would be both scientifically weak and overly personalized.

The evidence supports a more useful interpretation:

> **Graph-assisted reasoning quality is sensitive to graph provenance, query procedure, traversal depth, semantic coverage, seed selection, proof-obligation representation, and the discipline used to separate graph-native evidence from source-derived conclusions.**

The current case therefore provides information not only about whether a graph helps, but about **what constitutes a sufficiently controlled graph-assisted intervention**.

This may become important to the study's eventual experimental design. A graph artifact being present is not enough. The procedure by which it is authenticated, queried, interpreted, and connected to proof determines the actual reasoning scope made available to the model.

---

## 18. Bottom line

The self-report explains the majority of the procedural divergence.

The implementing/evaluating LLM:

- started from runtime-derived hypotheses;
- queried an unprovenanced 1,239-node / 3,717-edge scratch artifact;
- used regex and one-hop `jq` inspection;
- did not run Ajenda's graph generator, impact analysis, proof selection, completeness generation, or architecture-decision process;
- used graph results primarily to localize modules/tests and observe graph-schema gaps;
- found the concrete runtime mechanisms mainly through later source/test inspection.

The independent evaluator:

- pinned the exact #496 canonical graph artifact;
- established its workflow provenance and exact 1,265-node / 3,818-edge state;
- applied transitive architectural-impact semantics to a fixed responsibility-bearing seed set;
- independently quantified broad blast radius;
- separated graph-native findings from source/test mechanisms;
- found additional cross-representation and proof-obligation issues during later source/test inspection.

The resulting overlap in root-cause findings is meaningful. The differences are also meaningful. They are now explainable without assuming one model simply reasoned "better" or "worse."

The next empirical question is whether these different diagnostic procedures produce measurably different implementation completeness, proof quality, blast-radius control, and downstream corrective-PR behavior.