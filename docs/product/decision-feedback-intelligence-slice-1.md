# Decision Feedback Intelligence — Slice 1

**Status:** Implemented (contracts + deterministic abilities)
**Cluster:** Decision feedback / single-episode learning signal
**Date:** 2026-08-08
**Depends on:** Decision Support, Outcome Intelligence Slice 1, Evaluation Intelligence Slice 1

## Intention

Given one prior decision, Ajenda can preserve and evaluate this sequence:

```text
what was known → what was recommended → what was executed → what was observed
→ how the decision held up → what candidate lesson warrants future investigation
```

The output is feedback from one episode. It is not learned knowledge, policy, memory,
or permission to modify future behavior.

> Observation ≠ pattern ≠ knowledge ≠ policy.

## Contracts

- `DecisionSnapshot` freezes decide-time inputs so hindsight cannot change quality.
- `DecisionExecutionObservation` distinguishes no execution, partial execution,
  exact execution, material variation, and unknown execution.
- `DecisionQualityAssessment` audits the selected option against its original scores.
- `DecisionEffectivenessEvaluation` combines quality, fidelity, outcome, attribution,
  evidence, and chronology under fail-closed rules.
- `ConfidenceCalibrationAssessment` measures calibration without changing confidence policy.
- `ConsequenceInventory` preserves expected, unexpected, and unresolved movement.
- `DecisionLearningSignal` is a frozen single-episode observation whose
  `is_knowledge` and `is_policy` fields are literal `false`.

## Time contract

`OutcomeEvaluation.observed_at` is the strongest resolved observation time and
`OutcomeEvaluation.observation_timing` preserves whether it was source-verified, derived,
caller-asserted, or unknown. `OutcomeEvaluation.evaluated_at` is when the evaluation artifact
was produced. They are not interchangeable. Caller-asserted chronology cannot earn supported
contribution.

Decision Feedback never infers an observation time from `evaluated_at`, unrelated event
times, or the current clock. For an executed recommendation, missing execution time,
missing outcome observation time, or an observation before execution yields
`not_evaluable` and a weak learning signal. An evaluation may be produced before or after
execution without proving when the underlying outcome occurred.

## Explicit algorithms

### `decision_quality_v1`

1. Inspect only `DecisionSnapshot` decide-time fields.
2. Require the recommendation to match an `option_scores.option_id` when scores exist.
   A missing selected row returns `inconclusive`; it never falls back to another option.
3. Measure criterion support, acknowledged gaps, inferred evidence, alternatives,
   confidence consistency, and whether the selected option was strongest.
4. Post-decision information is retained only on the learning signal and cannot upgrade quality.

### `decision_effectiveness_v1`

The algorithm applies gates in this order:

1. Not executed receives no credit; unknown execution is insufficient evidence.
2. Unknown or impossible chronology is not evaluable.
3. Insufficient outcome evidence fails closed.
4. Materially varied execution cannot evaluate the original recommendation.
5. Missing, unearned, or conflicting attribution prevents effectiveness claims.
6. Partial execution with less than supported contribution is not evaluable as the
   original recommendation. Supported partial execution is capped at partial effectiveness.
7. Weak or unsupported decision quality caps a positive episode at partial effectiveness;
   inconclusive quality blocks strong positive effectiveness entirely.
8. Only exact execution, achieved outcome, supported contribution, and sufficiently
supported decide-time quality can become `highly_effective`. The outcome contract requires
the supported contribution level to match an earned attribution evidence artifact.
9. Negative outcomes remain observable: exact execution plus supported contribution and
   regression can become `counterproductive` without becoming knowledge or policy.

### `confidence_calibration_v1`

Calibration is assessable only when execution and attribution justify comparison. Material
variation, missing execution, and weak/conflicting attribution return `not_assessable`.
The result measures the episode; it does not rewrite future confidence behavior.

### `decision_learning_signal_v1`

- `weak`: not executed, not evaluable, insufficient evidence, or weak/conflicting attribution.
- `candidate`: temporal association or a bounded partial episode.
- `supported`: a strongly evidenced positive or counterproductive episode with supported
  contribution. “Supported” describes this episode only; it is not universal truth.

Every signal includes scope and invalidation conditions. Repetition and pattern promotion
belong to Experience Intelligence, not this slice.

## Abilities

- `analysis.evaluate_decision_effectiveness`
- `analysis.extract_decision_learning_signal`

Both are registered with `SideEffectClass.NONE`, require action-result evidence, and have
matching `AbilityManifest` entries. They do not persist, execute, dispatch, compose, or
alter runtime behavior.

## Boundaries

This slice does not add a StrategyEngine, persistence or memory promotion, behavior
auto-modification, composition/runtime wiring, causal inference, multi-episode pattern
learning, or any change to `weighted_criterion_evidence_v1`.

## Proof

Adversarial tests cover lucky outcomes, missing selected scores, impossible and unknown
chronology, evaluation-time separation, hindsight isolation, material variation, partial
execution with weak attribution, counterproductive observations, immutable knowledge/policy
flags, action evidence, and manifest rollout alignment.

## Files

- `backend/services/ontology/decision_feedback.py`
- `backend/services/ontology/outcome.py`
- `backend/services/tools/analysis_actions.py`
- `backend/services/abilities/catalog.py`
- `tests/unit/ontology/test_decision_feedback.py`
- `tests/unit/ontology/test_outcome.py`
