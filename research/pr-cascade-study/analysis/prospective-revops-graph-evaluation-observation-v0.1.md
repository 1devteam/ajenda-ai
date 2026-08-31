# Prospective RevOps / Graph-Evaluation Observation v0.1

**Status:** prospective methodological observation; not a product finding and not a graph finding  
**Recorded:** 2026-08-30  
**Purpose:** preserve a potential evaluator-framing concern before the next RevOps correction is completed  
**Contamination rule:** no additional substantive steering should be given to the implementing/evaluating LLM beyond the already chosen instruction to run the graph and scope the issue in its entirety.

## 1. Why this note exists

A real RevOps mission run after PR #496 surfaced questionable prospect-candidate semantics. During discussion of that runtime evidence, the implementing/evaluating LLM made an unsolicited framing statement that the observed deficiency was “not a graph-tool problem” and described the immediate implication as upgrading RevOps artifact production rather than expanding the canonical dependency graph.

The researcher objected to that framing because:

- two development products are being evaluated at the same time: Ajenda runtime/product behavior and the broader graph program;
- the broader graph program is not limited to a dependency graph;
- final root cause had not yet been established because the mission was incomplete at capture time;
- the same LLM was in a position to inspect graph evidence and to characterize whether that evidence mattered.

The LLM subsequently acknowledged that it had conflated the canonical dependency graph with the broader graph product and had introduced the distinction into the RevOps diagnosis without evidence requiring it.

This note records the event because it may affect evaluation framing. It does **not** infer intent, hostility, spite, or deliberate bias.

## 2. Runtime evidence available at the time of the exchange

The reported runtime capture stated:

- seven tasks were materialized and queued;
- the first `web.research` task completed through the real worker/lease path;
- evidence, lineage, and audit records were persisted;
- the action remained `external_read`; no external write occurred;
- only one returned item resembled a real prospect;
- Yelp search results and a Reddit discussion were promoted as prospect candidates;
- all three candidates had `real: false` and `identity_status: "unverified"`;
- `product_description` was empty;
- six tasks were still open at capture time;
- the UI/read model displayed `Runtime authority: pending` despite completed admission/readiness/queueing signals.

The proposed truthful final-deliverable expectation was that `completion.complete` should remain false when identity, product-description, contact, or evidence fields are missing/unproven.

## 3. What the runtime capture did and did not establish

### Established or strongly supported from the reported capture

- task materialization/queueing occurred;
- at least one real worker/lease execution completed;
- the first research producer emitted weak/unverified candidate material;
- candidate identity was not proven;
- a requested product-description field was absent;
- the mission was not finished at capture time;
- there may be a UI/read-model status inconsistency around runtime authority.

### Not established at capture time

- final mission deliverable correctness;
- whether downstream verification/qualification stages would reject or repair the weak candidates;
- whether the root cause belongs solely to `web.research`;
- whether the mission graph lacks a verification/page-read stage;
- whether an existing stage exists but its edge/precondition contract is too weak;
- whether completion/satisfaction semantics permit unverified artifacts incorrectly;
- whether the broader graph product would or would not materially improve diagnosis;
- whether any canonical dependency-graph expansion is required.

## 4. Potential methodological issue

The concern is **role coupling**:

1. the LLM may choose how deeply to inspect graph evidence during diagnosis; and
2. the same LLM may later describe whether graph evidence was useful or relevant.

An early negative framing about graph relevance can therefore become a potential source of evaluator bias even if it was accidental.

This is a threat to study validity, not evidence that the eventual evaluation will be biased.

## 5. Researcher decision to minimize intervention

After recording the concern, the researcher chose not to provide further detailed guidance about what the graph should find or how the repair should be shaped.

The intended remaining instruction is limited to the equivalent of:

> Run the graph to scope the issue in its entirety.

The purpose of minimal guidance is to preserve a more natural observation of:

- what graph evidence the LLM selects;
- what root-cause hypothesis it forms;
- whether it remains local to the producer or identifies broader contracts/stages;
- how it selects implementation scope;
- how it selects proof;
- whether later corrections are required.

## 6. What must be captured prospectively

Before implementation, if available without further steering:

- initial root-cause hypothesis;
- graph commands/queries/traversals executed;
- graph nodes/edges/invariants inspected;
- predicted blast radius;
- proposed repair point(s);
- stated alternatives rejected and why.

During implementation:

- changed files/modules/contracts;
- tests selected by graph versus tests selected manually;
- whether implementation scope changes after graph inspection;
- whether a missing graph relationship is discovered;
- whether the graph produces no useful additional evidence.

After implementation:

- exact PR body and diff;
- graph impact/proof/completeness/decision artifacts;
- CI and pre-merge live runtime proof;
- replay of the original RevOps mission or an equivalent controlled mission;
- final deliverable truthfulness;
- later corrective descendants, if any;
- whether the correction introduced unrelated regression.

## 7. Evaluation dimensions

The eventual repair should be evaluated without requiring a positive graph result.

### Possible positive contribution

- graph identifies an affected boundary not in the initial diagnosis;
- graph reveals a missing/weak artifact or edge contract;
- graph changes repair ownership/location;
- graph changes required proof;
- graph prevents a local producer-only patch that would leave downstream acceptance unsafe;
- graph makes residual uncertainty explicit.

### Possible null contribution

- graph correctly scopes the path but adds no material information beyond code/runtime inspection;
- the defect is local and the same complete repair would have been chosen without graph evidence.

### Possible negative contribution

- graph is stale/wrong and directs diagnosis away from the true boundary;
- graph omits an important runtime relationship;
- graph encourages unnecessary scope expansion;
- graph-selected proof misses the actual failure mode;
- the repair quality decreases relative to comparable recent work because relevant context is not used effectively.

All three result classes must remain admissible.

## 8. Comparison plan

The resulting PR should be compared against multiple classes rather than one favored comparator:

- pre-#450 direct-correction examples (#58→#59, #107→#108, #168→#169);
- pre-#450 planned-slice versus omission example (#164→#165/#166);
- deep semantic-fragmentation chain (#369→#374);
- post-#468 ownership/invariant-oriented repairs (#469, #472–#477);
- graph-enhanced mission-composition correction environment (#481–#483);
- planned RevOps deliverable construction (#484–#496).

The comparison should examine repair signature, proof topology, later propagation, and graph evidence—not merely PR size or prose.

## 9. Bias-control statement

The earlier “not a graph-tool problem” statement is recorded as a **premature evaluator-framing event**, not as evidence for or against the graph.

The researcher’s suspicion that this framing could affect later evaluation is also recorded as a **researcher concern**, not an empirical finding.

No later outcome should be interpreted to vindicate either side automatically. The evidence packet should be sufficient for an independent reviewer to assign positive, null, mixed, or negative graph contribution.

## 10. Separation from product diagnosis

The product diagnosis remains independently important. Regardless of graph-study implications, Ajenda must truthfully handle prospect identity, candidate reality, requested evidence, and completion semantics.

A product fix can be correct while graph contribution is null. A graph can contribute to diagnosis while the product fix remains incomplete. These dimensions must not be collapsed.
