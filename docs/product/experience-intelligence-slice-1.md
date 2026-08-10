# Experience Intelligence — Slice 1

**Status:** Implemented (contracts + deterministic abilities)
**Cluster:** Multi-episode comparison and recurrence candidate
**Date:** 2026-08-10
**Depends on:** Decision Feedback Intelligence Slice 1, Observation & Attribution Integrity Slice 1

## Intention

Given multiple prior decision episodes (each already reduced to a `DecisionLearningSignal`),
Ajenda can answer:

```text
are these episodes comparable?
are they independent?
do supporting and contradicting signals recur under shared scope?
what candidate pattern(s) are warranted — without promoting to knowledge or policy?
```

The output is a multi-episode observation. It is not learned knowledge, policy, memory,
or permission to modify future behavior.

> Observation ≠ pattern ≠ knowledge ≠ policy.

## Contract (V1 fail-closed)

- **Recommendation class** is the intervention identity. Missing → hard exclude from recurrence.
  Different classes → separate partitions. Never infer from prose.
- **Subject semantic class** = BusinessObjectType; instance ID is independence only.
- **Goal:** same goal_id strongest; missing goal_id + identical typed objective dimensions
  → PARTIALLY_COMPARABLE (EMERGING max); otherwise exclude.
- Multi-candidate output: `pattern_candidates` list (zero / one / many).
- `is_knowledge=False`, `is_policy=False` literal on every candidate.

## Algorithms

1. `experience_signature_v1` — comparison-relevant signature per episode
2. `experience_partition_v1` — group by intervention + subject type + goal/objective
3. `experience_independence_v1` — within each partition
4. `experience_recurrence_v1` — support / contradiction only inside eligible partitions
5. `experience_pattern_candidate_v1` — one candidate per eligible partition

## Abilities

- `analysis.compare_experiences`
- `analysis.assess_experience_recurrence`

Both SideEffectClass.NONE, evidence-required. No persistence, execution, composition, or runtime wiring.

## Boundaries

No Experience→knowledge promotion, StrategyEngine, composition/runtime wiring, or changes to
single-episode Decision Feedback / Attribution Integrity contracts.

## Files

- `backend/services/ontology/experience_intelligence.py`
- `backend/services/ontology/__init__.py`
- `backend/services/tools/analysis_actions.py`
- `backend/services/abilities/experience_manifests.py`
- `backend/services/abilities/catalog.py`
- `tests/unit/ontology/test_experience_intelligence.py`
- `tests/unit/abilities/test_ability_catalog.py`
- `docs/product/experience-intelligence-slice-1.md`
