# Experience Intelligence Slice 1

Experience Intelligence Slice 1 ships deterministic **Experience Equivalence & Recurrence Eligibility** for `DecisionLearningSignal` observations. It compares episodes and emits candidate recurrence observations only. It does not create knowledge, policy, memory, planner behavior, ability selection, or decision-weight changes.

Protected invariants:

- `episode ≠ recurrence ≠ pattern candidate ≠ knowledge ≠ policy`
- `instance identity ≠ semantic identity ≠ context ≠ equivalence ≠ independence`

## Runtime shape

`ExperienceEpisodeInput` wraps a `DecisionLearningSignal` with structured recurrence semantics that are not safely inferable from prose, including `recommendation_class`, typed `objective_dimensions`, attribution evidence IDs, chronology provenance, and lineage IDs.

Each episode derives an `ExperienceContextSignature` with separate surfaces for:

- Exact identity: signal ID, decision ID, subject instance refs, and exact goal ID.
- Semantic identity: canonical subject types, recommendation class, exact goal or typed objective dimensions, decision algorithm, effective/ineffective dimensions, attribution/provenance, scope, and invalidation conditions.

Free-form lesson or recommendation prose is not used to infer semantic equivalence.

## Deterministic processing order

The implementation performs:

1. `DecisionLearningSignal` episode input validation.
2. `ExperienceContextSignature` derivation.
3. Semantic partitioning before recurrence.
4. Independence assessment inside each partition.
5. Support, contradiction, and neutral classification.
6. Recurrence assessment per partition.
7. Zero, one, or many `ExperiencePatternCandidate` outputs.

The full input set is never forced into one global pattern.

## Semantic rules

- Subject type/class is part of comparability. Different instances of the same canonical type, such as `opportunity:A` and `opportunity:B`, can be comparable.
- Subject instance identity is a dependence/correlation signal. Repeated observations of the same exact object are inspectable and do not become stronger recurrence just by repetition.
- Different canonical subject types, such as `opportunity` and `account`, are incompatible unless future structured contracts explicitly earn equivalence.
- `recommendation_class` is a hard recurrence requirement. Missing values are unclassified, never converted to `unknown`, and never support or contradict a candidate.
- Different recommendation classes create separate partitions.
- Same exact `goal_id` is strongest goal comparability. Missing/different goal IDs require typed objective dimensions to establish deterministic equivalence; free-form goal prose is ignored.

## Independence, attribution, and counterexamples

Independence is assessed separately from comparability. Duplicate signal IDs, duplicate decision IDs, overlapping evidence IDs, repeated exact subject instances, and reused lineage are surfaced as dependent or partially independent groups. Unknown independence is not treated as independent.

Attribution quality survives aggregation. Supported contribution is stronger than temporal association, caller assertions, insufficient attribution, or conflicting evidence. Weak attribution caps recurrence strength, and caller-asserted provenance cannot manufacture supported recurrence.

Counterexamples are symmetric and partition-local: incompatible episodes cannot poison a partition merely because their effectiveness differs. Comparable support plus contradiction yields contested recurrence; repeated comparable contradiction can invalidate the candidate.

## Candidate output and safety

`ExperienceIntelligenceResult.pattern_candidates` is a list. Each candidate exposes supporting, contradicting, neutral, excluded, dependent, scope, invalidation, and temporal-span fields. `unclassified_episode_ids`, `excluded_episode_ids`, dependent groups, and partition explanations remain inspectable at the result level.

Every `ExperiencePatternCandidate` is frozen and enforces:

- `is_knowledge=False`
- `is_policy=False`

These flags cannot be overridden through deserialization. Candidates remain bounded observations and do not persist memory, modify weights, modify policy, trigger replanning, execute actions, or perform causal inference.

## Ability actions

Slice 1 registers non-side-effecting analysis actions:

- `analysis.compare_experiences` returns signatures, comparisons, partitions, unclassified IDs, and dependent groups without requiring any candidate to exist.
- `analysis.assess_experience_recurrence` returns the complete multi-candidate `ExperienceIntelligenceResult`.

Both use provider `ajenda_analysis`, `SideEffectClass.NONE`, `evidence_required=true`, and `action_result_evidence`.

## Temporal preservation

Candidates preserve earliest and latest deterministic `evaluated_at` timestamps across partition episodes. This is for later qualification only; Slice 1 does not implement recency weighting or temporal decay.

## Explicit non-goals

This slice does not add cross-layer semantic coherence, global evidence lineage redesign, new goal objective-key persistence, knowledge intelligence, experience-to-knowledge promotion, memory persistence, decision-weight adaptation, StrategyEngine, ability graph, planner/replanner wiring, LLM classification, causal inference, or DB migrations.
