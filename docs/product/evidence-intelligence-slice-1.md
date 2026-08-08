# Evidence Intelligence — Slice 1

**Status:** Implemented (ability surface only)  
**Cluster:** Evidence Intelligence / Decision Support  
**Date:** 2026-08-08  

## Target capability

Ajenda can score candidate options against explicit criteria using supplied evidence facts and produce a defensible next-action recommendation with confidence, uncertainty, and change conditions.

This slice does **not**:

- execute the recommendation
- wire composition → mission bridge → runtime
- introduce StrategyEngine
- replace `sales.recommend_next_action`

## Ability delivered

| Action | Provider | Side effect | Notes |
|--------|----------|-------------|-------|
| `decision.recommend_next_action` | `ajenda_decision` | `none` | Deterministic weighted criterion scoring |

## Contracts

Defined in `backend/services/tools/schemas.py`:

- `EvidenceFactStatus` — `known` | `inferred` | `missing`
- `EvidenceFact` — claim, status, source, confidence, option/criterion linkage
- `DecisionOption` — option_id, label, description
- `DecisionCriterion` — criterion_id, label, weight, required
- `DecisionRecommendInput` — goal, options, criteria, evidence, constraints

## Algorithm (forced open)

`weighted_criterion_evidence_v1`:

1. Normalize criterion weights to sum 1.
2. For each option × criterion, select linked facts (by `supports_criterion_ids` and optional `supports_option_ids`).
3. Contribution: known = `1.0 * confidence`, inferred = `0.6 * confidence`, missing = `0.0`.
4. Required criteria with no supporting known/inferred fact create gaps.
5. Constraints matching `forbid:<option_id>` or `must not <option_id>` mark option infeasible (score forced to 0).
6. Rank feasible options by `(total_score, confidence)`.
7. If no options or no feasible positive score → recommend `gather_more_evidence`.
8. Output always includes supporting evidence ids, uncertainty flags, and `what_would_change_recommendation`.

## Deferred (same cluster, later slices)

- `research.collect_evidence`
- `research.synthesize`
- `analysis.compare_options`
- `analysis.score` as standalone ability (scoring is embedded in recommend for Slice 1)

## Files

- `backend/services/tools/schemas.py` — contracts
- `backend/services/tools/decision_actions.py` — handler + register
- `backend/services/tools/action_registry.py` — register_decision_actions
- `backend/services/abilities/catalog.py` — AbilityManifest
- `tests/unit/tools/test_decision_actions.py`
- `docs/product/evidence-intelligence-slice-1.md` (this file)
