# Commercial State / Goal / KPI — Ontology Slice 2

**Status:** Implemented (contracts only)  
**Cluster:** Commercial state + objectives + measurement  
**Date:** 2026-08-08  
**Depends on:** Business Ontology Slice 1, Evidence Intelligence Slice 1

## Target capability

Ajenda can represent:

- what an Account / Contact / Lead / Opportunity currently looks like (state),
- what desired outcome applies to it (goal),
- what measurable indicators define progress (KPI),
- what observations changed its state (event),
- while keeping evidence as a separate proving layer.

This enables the business-native question:

> Given Opportunity X, Goal Y, current KPI state, and the latest evidence, what is the most defensible next action?

## Hard separations

| Concept | Is | Is not |
|---------|----|--------|
| **Evidence** | Source-backed claim with confidence | Operating state |
| **BusinessEvent** | Something that happened / may have changed state | State itself; not evidence |
| **BusinessStateSnapshot** | Point-in-time believed representation | System-of-record mutation; not evidence |
| **KPI** | Measurable indicator on a Goal | Evidence; not a goal |
| **Goal** | Desired change / outcome | Business object identity (Account, Opp, …) |

Example chain:

1. Gmail message `msg_442` → **Evidence**  
2. "Jane replied positively" → **BusinessEvent** (evidence_ids cite msg_442)  
3. Attributes `buyer_engagement=high` → **BusinessStateSnapshot**  
4. `qualification_score current=62 target=80` → **KPI**  
5. "Qualify by Aug 31" → **Goal**

## Contracts

| Model | Module | Key fields |
|-------|--------|------------|
| `Goal` | `ontology/commercial_state.py` | goal_id, name, description, subject_refs, status, target_date |
| `Kpi` | same | kpi_id, goal_id, name, metric, direction, target/current value, unit |
| `BusinessStateSnapshot` | same | snapshot_id, subject_ref, captured_at, attributes, evidence_ids |
| `BusinessEvent` | same | event_id, event_type, subject_refs, occurred_at, evidence_ids, payload |

`DecisionRecommendInput` optional fields (non-breaking):

- `subject_refs`
- `goal_ref`
- `kpis`
- `state_snapshot`
- `recent_events`

`decision.recommend_next_action` echoes these under `output.commercial_context` when present. **Scoring algorithm remains `weighted_criterion_evidence_v1`** — commercial context does not alter v1 scores.

## Relationship to light_crm Activity

`BusinessEvent.event_type` may align with light_crm `ActivityType` (`email_sent`, `stage_changed`, …) without replacing CRM activity storage. Activity continues to live in the vertical; ontology event is the reasoning contract.

## Explicit non-goals (this slice)

- KPI optimization engine
- Automatic goal mutation
- Recommendation execution
- Longitudinal learning
- Event ingestion from every runtime system
- Graph database
- StrategyEngine
- Composition → runtime wiring

## Next cluster (not this PR)

**Evaluation Intelligence** abilities such as:

- `analysis.evaluate_goal_progress`
- `analysis.detect_state_change`
- `analysis.compare_kpi_to_target`
- `decision.identify_next_gap`

## Sequence reminder

Evidence Intelligence → Business Objects → **Goal / KPI / State / Event** → Evaluation Intelligence → vertical abilities → ability relationships → planning algorithms → system-wide wiring.

## Files

- `backend/services/ontology/commercial_state.py`
- `backend/services/ontology/__init__.py`
- `backend/services/tools/schemas.py` — optional DecisionRecommendInput fields
- `backend/services/tools/decision_actions.py` — commercial_context echo
- `tests/unit/ontology/test_commercial_state.py`
- `docs/product/commercial-state-goal-kpi-slice-2.md` (this file)
