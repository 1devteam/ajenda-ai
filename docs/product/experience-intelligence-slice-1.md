# Experience Intelligence Slice 1

Experience Intelligence Slice 1 ships deterministic **Experience Equivalence & Recurrence Eligibility** for `DecisionLearningSignal` observations. It compares episodes and emits recurrence candidates only when recurrence has been earned by eligible, semantically comparable, dependence-resolved evidence units. It does not create knowledge, policy, memory, planner behavior, ability selection, or decision-weight changes.

Protected invariants:

- `episode ≠ recurrence ≠ pattern candidate ≠ knowledge ≠ policy`
- `instance identity ≠ semantic identity ≠ lineage ≠ context ≠ equivalence ≠ independence`

## Runtime shape

`ExperienceEpisodeInput` wraps a `DecisionLearningSignal` with explicit V1 recurrence metadata: `recommendation_class`, caller-context `objective_dimensions`, attribution evidence IDs, observation-time provenance, and lineage IDs. Decision-owned `intervention_key` is authoritative; `recommendation_class` remains transitional V1 metadata and conflicts fail closed.

Each episode derives an `ExperienceContextSignature` with separate surfaces for:

- Exact identity: signal ID, decision ID, subject instance refs, and exact goal ID.
- Semantic identity: owner-produced subject, Goal/KPI, intervention, and evidence-lineage semantics, plus scope, algorithm identity, execution fidelity, attribution, and observation provenance.

`objective_dimensions` are preserved as caller context only. They never outrank owned Goal/KPI signatures and cannot infer equivalence from arbitrary strings or prose.

## Deterministic processing order

The implementation performs:

1. Input validation, including duplicate `episode_id` rejection.
2. Canonical signature derivation with sorted set-like fields.
3. Conservative semantic partitioning by authoritative intervention key, subject class, owner Goal/KPI semantics, and exact scope set.
4. Per-episode recurrence eligibility classification.
5. Dependence graph construction across each full partition before support/contradiction classification.
6. Dependence-resolved evidence-unit classification as support, contradiction, neutral, or ambiguous.
7. Recurrence assessment per partition.
8. Zero, one, or many `ExperiencePatternCandidate` outputs.

The result is stable under episode ordering and subject/scope/evidence set ordering. Singleton partitions and hard-dependent copies do not automatically become pattern candidates.

## Semantic rules

- Subject type/class is part of comparability. Different instances of the same canonical type, such as `opportunity:A` and `opportunity:B`, can be comparable.
- Subject instance identity is a dependence/correlation signal. Repeated observations of the same exact object are inspectable and do not become stronger recurrence just by repetition.
- Different canonical subject types, such as `opportunity` and `account`, are incompatible unless future structured contracts explicitly earn equivalence.
- Decision-owned `intervention_key` is preferred and never inferred from recommendation prose. Transitional `recommendation_class` is used only when owner semantics are absent; disagreement is ineligible.
- Different intervention keys create separate partitions.
- The same exact goal is strongly comparable. Different goal IDs compare through equal explicit `objective_key`; identical owned KPI signatures earn partial comparison only and cap recurrence. Missing semantics remain insufficient.
- When both owner Goal signatures exist, they are compared before exact `goal_id`. Conflicting
  explicit objective keys fail closed even when the artifacts name the same goal instance.
- Goal partition identity is resolved once before comparison and partitioning. Legacy observations
  may inherit one unambiguous owner identity from the same exact goal instance; conflicts are
  unclassified rather than split into misleading partitions.
- Exact scope-condition sets are part of V1 partitioning. Different non-empty scopes do not silently aggregate. Unscoped episodes do not strengthen scoped claims to `SUPPORTED`.

## Eligibility, independence, and evidence units

A semantic partition is only a bucket. A pattern candidate requires at least two directional recurrence evidence units after eligibility and dependence resolution.

Per-episode eligibility distinguishes:

- Strong recurrence evidence: executed as recommended, supported learning signal, supported attribution, and eligible provenance.
- Limited recurrence evidence: temporal association, caller-asserted/unknown/derived chronology, partial execution, weak or candidate learning-signal strength.
- Ineligible evidence: non-execution, execution unknown, material variation, conflicting/insufficient/not-assessed attribution, or active invalidation conflicts.

Independence is assessed separately from comparability and before outcome direction. Duplicate signal IDs, duplicate decision IDs, shared lineage roots/sources/ancestors, and derivation form hard-dependent components. Partially resolved lineage and repeated exact subject instances are partial/correlation signals; unknown lineage is indeterminate, never independent. A hard-dependent component with positive and negative recomputations is ambiguous, not independent support plus an independent counterexample.

## Attribution, provenance, execution, and counterexamples

Attribution and provenance quality survive aggregation per episode. Caller-asserted or unknown chronology cannot manufacture `SUPPORTED` recurrence through repetition. Temporal association and weak/candidate learning signals can contribute limited evidence but not strong support. Recurrence assessments expose these cross-cutting constraints through `evidence_limitation`; the field is not narrowly or misleadingly labeled as an attribution-only cap.

Execution fidelity is part of recurrence eligibility. `NOT_EXECUTED` is not a counterexample to intervention effectiveness; it is excluded as non-execution. Execution unknown and material variation are also excluded from same-intervention recurrence evidence. Partial execution is limited evidence.

Counterexamples are partition-local, dependence-resolved, and quality-tiered symmetrically with support. Strong independent support plus a strong independent contradiction yields contested recurrence. Only repeated strong independent contradictions can invalidate a candidate. Limited or dependent contradictions remain inspectable but cannot gain invalidation authority through repetition. Incompatible or singleton contradictions do not poison unrelated partitions.

## Candidate output and safety

`ExperienceIntelligenceResult.pattern_candidates` is a list. Each candidate exposes supporting, contradicting, neutral, ambiguous, excluded, dependent, scope, invalidation, and evaluation-time-span fields. Caller-supplied `objective_dimensions` are emitted only when identical across the entire partition; divergent caller context is omitted and explained rather than inherited from an arbitrary first episode. `unclassified_episode_ids`, `excluded_episode_ids`, dependent groups, partition explanations, and episode explanations remain inspectable at the result level.

Opaque evidence and lineage identifiers are trimmed, deduplicated, and sorted without case folding. Semantic labels use canonical case-insensitive normalization, but identity-bearing values preserve exact case unless their owning contract explicitly defines otherwise.

Every `ExperiencePatternCandidate` is frozen and enforces:

- `is_knowledge=False`
- `is_policy=False`

These flags cannot be overridden through deserialization. Candidates remain bounded observations and do not persist memory, modify weights, modify policy, trigger replanning, execute actions, or perform causal inference.

## Ability actions

Slice 1 registers non-side-effecting analysis actions:

- `analysis.compare_experiences` returns signatures, comparisons, unclassified IDs, excluded IDs, dependent groups, and partition explanations without requiring any candidate to exist. Its summary reports semantic partitions separately from emitted candidates.
- `analysis.assess_experience_recurrence` returns the complete multi-candidate `ExperienceIntelligenceResult`.

Both use provider `ajenda_analysis`, `SideEffectClass.NONE`, `evidence_required=true`, and `action_result_evidence`.

## Temporal preservation

Candidates preserve earliest and latest deterministic `evaluated_at` timestamps as `earliest_evaluated_at` and `latest_evaluated_at`. Slice 1 does not claim these are observation timestamps, and it does not implement recency weighting or temporal decay.

## Explicit non-goals

This slice consumes cross-layer semantic coherence but still does not add independent source verification, Knowledge Qualification, experience-to-knowledge promotion, memory persistence, decision-weight adaptation, StrategyEngine, ability graph, planner/replanner wiring, LLM classification, causal inference, or behavior changes.

## Typed downstream semantic boundary

Experience now emits an additive, frozen `ExperiencePatternSemanticContext` on each produced candidate. It preserves typed Business Ontology subject classes, Decision intervention authority basis, Goal objective/KPI authority basis (including inherited and exact-instance compatibility distinctions), exact Goal provenance, common scope, and invalidation conditions. This context describes the same population used for partitioning and remains Experience-owned. Compatibility fields are unchanged, but downstream Knowledge Qualification must consume the typed boundary and fail closed when it is absent rather than reconstructing semantics from strings. Experience itself remains candidate-only and does not qualify knowledge.
