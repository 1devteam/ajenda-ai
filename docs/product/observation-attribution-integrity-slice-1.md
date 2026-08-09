# Observation & Attribution Integrity — Slice 1

**Status:** Implemented (contracts + deterministic analysis ability)
**Cluster:** Observation chronology / non-causal attribution
**Date:** 2026-08-08
**Depends on:** Outcome Intelligence Slice 1 and Decision Feedback Intelligence Slice 1 (PR #412)

## Purpose

This slice prevents two caller assertions from masquerading as verified intelligence:

1. when an outcome was observed; and
2. whether an executed action made a supported contribution to that outcome.

It is a read-model analysis layer. It does not verify an external system independently,
persist evidence, infer causation, execute work, or alter future decisions.

## Observation chronology

`resolve_observation_timing` selects the strongest available timestamp and preserves every
input on an immutable `ObservationTiming` artifact:

1. `source_observed_at` → `source_verified`
2. `captured_at` → `derived`
3. `asserted_observed_at` (or legacy `observed_at`) → `caller_asserted`
4. no timestamp → `unknown`

`captured_at` is explicitly a derived observation bound, not source-reported truth.
All chronology used by this slice must be timezone-aware. Caller-asserted and unknown
chronology cannot support an earned contribution assessment.

## Attribution evidence and algorithm

`AttributionEvidenceInput` carries:

- execution time and execution evidence IDs;
- expected and observed change dimensions;
- competing explanations;
- conflicting evidence IDs; and
- bounded confidence.

`attribution_evidence_v1` produces immutable `AttributionAssessmentEvidence` with resolved
ordering, matching dimensions, explanation codes, resulting attribution, and
`causal_claim=false`.

The evaluator is deterministic and fail-closed:

- conflicting evidence or observation before execution → `conflicting_evidence`;
- missing execution proof, unverifiable chronology, missing dimensions, or no dimension
  match → `insufficient_evidence`;
- derived chronology, or verified ordering plus a matching dimension but a competing
  explanation or confidence below `0.7` → `temporal_association`;
- execution proof, source-verified ordering, matching expected/observed dimensions, no
  competing/conflicting evidence, and confidence of at least `0.7` →
  `supported_contribution`.

Temporal order, repeated association, and supported contribution are all non-causal.
There is no causal attribution value and no promotion rule from repetition.

## Outcome and feedback integration

`ObservedOutcome` accepts the provenance-aware timestamps. `OutcomeEvaluation` carries the
resolved `ObservationTiming` and optional earned `AttributionAssessmentEvidence`.
`supported_contribution` cannot be constructed on `OutcomeEvaluation` without a matching
earned artifact. A legacy caller assertion of supported contribution passed to
`evaluate_outcome` is downgraded to `insufficient_evidence` with explicit explanation codes.

Decision Feedback continues consuming `OutcomeEvaluation.attribution`; the model invariant
now guarantees that supported contribution is earned when present. No composition or
runtime wiring is added.

## Ability

`analysis.assess_attribution_integrity` is registered with `SideEffectClass.NONE`, emits an
`EvidenceItem`, and has a matching ability manifest. `analysis.evaluate_outcome` also accepts
the new timing and attribution-evidence fields.

## Boundaries and rollback

Non-goals: causal inference, source-system verification, persistence, memory promotion,
Experience Intelligence aggregation, StrategyEngine, auto-learning, decision-weight
changes, composition/runtime wiring, execution, and changes to
`weighted_criterion_evidence_v1`.

The change is additive except for the intentional integrity rule that rejects forged
`supported_contribution`. Rollback is code-only: remove the new action/manifest and restore
the V1 caller-attribution behavior. No schema migration or stored-data rollback is required.

## Proof

Adversarial tests cover precedence, derived/caller/unknown provenance, naive timestamps,
reversed chronology, missing execution proof, mismatched dimensions, competing explanations,
conflicts, confidence thresholding, forged supported contribution, earned downstream
consumption, action evidence, and manifest alignment.
