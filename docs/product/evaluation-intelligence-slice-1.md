# Evaluation Intelligence — Slice 1

**Status:** Implemented (contracts + deterministic ability)  
**Cluster:** Evaluation / assessment  
**Date:** 2026-08-08  
**Depends on:** Evidence Intelligence Slice 1, Business Ontology Slice 1, Commercial State Slice 2

## Target capability

Given Goal + KPI + state (+ optional previous state, events, evidence ids),
Ajenda produces an **EvaluationResult**: present situation and what blocks progress.

Not autonomous action selection. Not StrategyEngine.

## Ability

`analysis.evaluate_goal_progress` — side-effect **NONE**

## Primitives

| Primitive | Function | Output |
|-----------|----------|--------|
| KPI evaluation | `evaluate_kpi` | gap, attainment, target_reached, change, explanation |
| Goal progress | `evaluate_goal_progress` | GoalProgressStatus + gaps |
| State comparison | `compare_state_snapshots` | added/removed/changed attributes |
| Gap identification | embedded | performance vs evidence vs information |

### GoalProgressStatus (V1 rules)

- **achieved** — all required KPIs meet target
- **off_track** — required KPI moved against direction, or gaps with no improvement
- **on_track** — required metrics improving/met, no evidence gaps
- **at_risk** — progress exists but required gaps remain
- **insufficient_data** — cannot justify stronger status

Every status carries inspectable `explanations` and gap codes.

## Separations

Evidence / State / Event / KPI / Goal / **Evaluation** / Decision remain distinct.

`weighted_criterion_evidence_v1` is **unchanged**. Evaluation does not auto-feed recommendation scoring.

## Contract cleanups (this pass)

- `Goal.target_date` → `date | None`
- `BusinessStateSnapshot.captured_at` / `BusinessEvent.occurred_at` → `datetime`
- `COMMERCIAL_RELATIONSHIP_SPECS` → `tuple[OntologyRelationshipSpec, ...]`
- `Kpi.required`, `Kpi.previous_value`, `Kpi.maintain_tolerance`

## Explicit non-goals

StrategyEngine, task creation, goal mutation, KPI ingestion pipelines, forecasting,
learned scoring, LLM judgment, graph DB, autonomous remediation, recommendation execution.

## Sequence

Observe → Evidence → State/Event → Goal/KPI → **Evaluate** → Decide → (later) Outcome Intelligence

## Files

- `backend/services/ontology/evaluation.py`
- `backend/services/ontology/commercial_state.py` (temporal + relationships + KPI fields)
- `backend/services/ontology/types.py` (`OntologyRelationshipSpec`)
- `backend/services/tools/analysis_actions.py`
- `backend/services/tools/action_registry.py`
- `tests/unit/ontology/test_evaluation.py`
- `docs/product/evaluation-intelligence-slice-1.md`
