# Mission Composition Function Graph

## Purpose

Ajenda's canonical dependency graph remains module-first. Mission composition is an explicit exception because interpretation defects can be owned by individual decision functions even when module-level dependencies are correct.

The selective function layer covers `backend/services/mission_composition/**/*.py` and is generated from Python ASTs. It does not expand unrelated subsystems into function nodes.

## Function node model

Function nodes use stable IDs:

`fn:<python-module>:<function-name>`

Each function node records its source module and source file. Intelligence-critical functions may also carry a `decision_role`, including:

- `segments_text`
- `classifies_materiality`
- `interprets_mission`
- `maps_outcome`
- `maps_fuzzy_outcome`
- `normalizes_text`

The role is diagnostic metadata, not execution authority.

## Edges

The selective layer adds:

- `defined_in` — function to owning Python module
- `calls_function` — statically resolved function call within the selected subsystem
- `tests_function` — direct named test import to a selected function

Existing module-level `imports` and `tests` edges remain unchanged. Function edges therefore refine the graph instead of replacing module ownership.

## Node-level impact analysis

`graph_impact_analysis.py` accepts `--changed-node` for focused diagnosis. For example:

```bash
python scripts/validation/graph_impact_analysis.py \
  --changed-node 'fn:backend.services.mission_composition.intent_interpreter:_classify_clause' \
  --json
```

This answers the function-level versions of the canonical graph questions: what calls this decision function, what it depends on, and which tests directly exercise it.

File-level analysis remains authoritative for ordinary PR change impact and proof selection. Node-level analysis is a diagnostic refinement and must not be used to hide other functions changed in the same source file.

## Scope discipline

Function-level expansion should remain selective. A subsystem should receive this treatment only when function-level decision ownership materially improves correctness, diagnosis, or proof selection. The default remains module-level graphing to avoid global graph noise and misleading pseudo-precision.
