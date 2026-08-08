# Outcome Intelligence — Slice 1

**Status:** Implemented (contracts + deterministic ability)  
**Cluster:** Outcome assessment  
**Date:** 2026-08-08  
**Depends on:** Evaluation Intelligence Slice 1, Commercial State Slice 2, existing OutcomeReview domain

## Target capability

Given baseline expectation + observed result for a Goal/KPI set, Ajenda produces an
**OutcomeEvaluation**: what changed, how much gap closed, what evidence justifies, and
what attribution level is allowed.

Not OutcomeReview persistence. Not autonomous learning. Not causation.

## Central distinction

| Layer | Question |
|-------|----------|
| Evaluation Intelligence | Where are we now relative to the goal? |
| Outcome Intelligence | What changed between expected/baseline and observed result? |

## Ability

`analysis.evaluate_outcome` — side-effect **NONE**

## Algorithm

`outcome_delta_v1`:

1. Pair baseline KPIs with observed KPIs by `kpi_id`
2. For each pair: absolute change, previous/remaining gap, gap closed, direction assessment
3. Compare state snapshots via existing `compare_state_snapshots`
4. Run `evaluate_goal_progress` on baseline and observed for inspectable before/after
5. Aggregate conservative `OutcomeStatus`
6. Record caller-supplied `AttributionAssessment` without inventing causation

### OutcomeStatus (V1)

- **achieved** — all measurable KPIs target_reached
- **partial_progress** — movement toward target (or mixed)
- **no_material_change** — measurable but unchanged
- **regressed** — movement away from target only
- **inconclusive** — residual ambiguous cases
- **insufficient_evidence** — missing values / evidence gaps dominate

### AttributionAssessment

- `not_assessed` (default)
- `temporal_association`
- `supported_contribution` (caller-asserted only)
- `conflicting_evidence`
- `insufficient_evidence`

**No `caused` value.** Causation is out of scope.

## Relationship to OutcomeReview

Existing `OutcomeReview` remains the durable evidence-backed review storage contract
(API, lifecycle, evidence validation, human approval). This slice produces a structured
`OutcomeEvaluation` that a **later explicit caller** may map into an OutcomeReview.

`analysis.evaluate_outcome` does **not** create, update, or enqueue OutcomeReview records.

## Explicit non-goals

Automatic OutcomeReview persistence, recommendation execution, mission wiring,
memory promotion, weight modification, StrategyEngine, causal inference, LLM judgment,
KPI forecasting, autonomous retry/replan.

## Files

- `backend/services/ontology/outcome.py`
- `backend/services/tools/analysis_actions.py`
- `backend/services/abilities/catalog.py`
- `tests/unit/ontology/test_outcome.py`
- `docs/product/outcome-intelligence-slice-1.md`
