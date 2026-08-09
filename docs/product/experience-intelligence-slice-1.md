# Experience Intelligence — Slice 1

**Status:** Implemented (contracts + deterministic abilities)
**Cluster:** Multi-episode comparison and recurrence candidate
**Date:** 2026-08-09
**Depends on:** Decision Feedback Intelligence Slice 1, Observation & Attribution Integrity Slice 1

## Intention

Given multiple prior decision episodes (each already reduced to a `DecisionLearningSignal`),
Ajenda can answer:

```text
are these episodes comparable?
are they independent?
do supporting and contradicting signals recur under shared scope?
what candidate pattern (if any) is warranted — without promoting it to knowledge or policy?
```

The output is a multi-episode observation. It is not learned knowledge, policy, memory,
or permission to modify future behavior.

> Observation ≠ pattern ≠ knowledge ≠ policy.

## Contracts

- `ExperienceEpisodeInput` wraps a `DecisionLearningSignal` plus optional provenance /
  algorithm / recommendation-class context so attribution quality can survive aggregation
  without rewriting #412/#413 contracts.
- `ExperienceComparabilityAssessment` fails closed on foreign goal/subject and surfaces
  algorithm / fidelity divergence.
- `ExperienceIndependenceAssessment` treats duplicate `decision_id` / `signal_id` and
  overlapping evidence lineage as first-class dependence.
- `ExperienceComparison` records set-level comparability and independence before any
  recurrence claim.
- `RecurrenceAssessment` requires visible counterexamples, preserves attribution floor,
  and never upgrades caller-asserted chronology into supported recurrence.
- `ExperiencePatternCandidate` is frozen with literal `is_knowledge=False` and
  `is_policy=False`.

## Explicit algorithms

### `experience_comparability_v1`

1. Require at least two episodes.
2. Reject foreign `goal_id` and incompatible subject sets.
3. Record shared algorithm lineage and execution fidelity class when uniform.
4. Dimension overlap is informational; it does not override goal/subject gates.

### `experience_independence_v1`

1. Duplicate `decision_id` or `signal_id` ⇒ dependent.
2. Overlapping `supporting_evidence_ids` ⇒ partially independent.
3. Independence is evaluated before recurrence strength is assigned.

### `experience_recurrence_v1`

1. Not comparable or dependent sets cannot establish recurrence (weak).
2. Weak / unearned attribution cannot inflate supporting counts.
3. Caller-asserted provenance cannot produce `supported` recurrence.
4. Counterexamples are mandatory and visible; balance or dominance yields `contested`;
   counterexamples without support yield `invalidated`.
5. Strength ladder: `weak` → `emerging` → `supported` → `contested` → `invalidated`.
   There is no “proven” state.

### `experience_pattern_candidate_v1`

- Scope and invalidation conditions are derived from episode fields and shared context.
- Attribution floor is the weakest attribution among contributing episodes.
- Pattern text is a candidate lesson only; flags remain literal false.

## Abilities

- `analysis.compare_experiences`
- `analysis.assess_experience_recurrence`

Both are registered with `SideEffectClass.NONE`, require action-result evidence, and have
matching `AbilityManifest` entries. They do not persist, execute, dispatch, compose, or
alter runtime behavior.

## Boundaries

This slice does not add Experience→knowledge promotion, policy writing, StrategyEngine,
persistence/memory, composition/runtime wiring, causal inference, or any change to
`weighted_criterion_evidence_v1` / single-episode Decision Feedback contracts.

## Proof

Adversarial tests cover: independent emerging/supported recurrence, foreign goal/subject
rejection, duplicate decision dependence, evidence overlap, contested and invalidated
sets, caller-asserted provenance caps, weak attribution non-inflation, single-episode
insufficiency, immutable knowledge/policy flags, and action registration evidence.

## Files

- `backend/services/ontology/experience_intelligence.py`
- `backend/services/ontology/__init__.py`
- `backend/services/tools/analysis_actions.py`
- `backend/services/abilities/catalog.py`
- `tests/unit/ontology/test_experience_intelligence.py`
- `tests/unit/abilities/test_ability_catalog.py`
- `docs/product/experience-intelligence-slice-1.md`
