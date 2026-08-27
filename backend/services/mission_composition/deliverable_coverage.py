"""Reconcile typed deliverable requests with interpretation coverage.

This module accounts only for explicit deliverable clauses already understood by
``extract_deliverable_request``. It does not map business outcomes, select jobs,
grant runtime authority, or materialize deliverables.
"""

from __future__ import annotations

from backend.services.mission_composition.contracts import MissionIntent, SemanticUnit
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request

_DELIVERABLE_ACCOUNTED_REASON = "Typed deliverable request accounted"


def reconcile_deliverable_coverage(intent: MissionIntent) -> MissionIntent:
    """Account fully understood deliverable clauses without weakening fail-closed coverage."""

    request = intent.deliverable_request
    if request is None or not request.fully_understood:
        return intent

    accounted_clause_ids: set[str] = set()
    reconciled_clauses = []
    for clause in intent.interpreted_clauses:
        if not clause.material or clause.status == "recognized":
            reconciled_clauses.append(clause)
            continue

        clause_request = extract_deliverable_request(clause.text)
        if clause_request is None or not clause_request.fully_understood:
            reconciled_clauses.append(clause)
            continue

        accounted_clause_ids.add(clause.clause_id)
        reconciled_clauses.append(
            clause.model_copy(
                update={
                    "status": "recognized",
                    "reason": _DELIVERABLE_ACCOUNTED_REASON,
                }
            )
        )

    if not accounted_clause_ids:
        return intent

    reconciled_units: list[SemanticUnit] = []
    for unit in intent.semantic_units:
        if unit.unit_id not in accounted_clause_ids:
            reconciled_units.append(unit)
            continue
        reconciled_units.append(
            unit.model_copy(
                update={
                    "kind": "deliverable",
                    "accounted": True,
                    "reason": _DELIVERABLE_ACCOUNTED_REASON,
                }
            )
        )

    unmatched_clauses = [clause for clause in reconciled_clauses if clause.material and clause.status != "recognized"]
    unmatched_units = [
        unit
        for unit in reconciled_units
        if unit.unit_id not in accounted_clause_ids
        and any(
            clause.clause_id == unit.unit_id and clause.material and clause.status != "recognized"
            for clause in reconciled_clauses
        )
    ]

    material_total = sum(1 for clause in reconciled_clauses if clause.material)
    material_ok = sum(1 for clause in reconciled_clauses if clause.material and clause.status == "recognized")
    coverage = (material_ok / material_total) if material_total else intent.coverage_score

    ambiguity = list(intent.ambiguity)
    if not unmatched_clauses and not unmatched_units:
        ambiguity = [item for item in ambiguity if item.field != "clause_coverage"]

    intent.interpreted_clauses = reconciled_clauses
    intent.unmatched_material_clauses = unmatched_clauses
    intent.semantic_units = reconciled_units
    intent.unmatched_material_units = unmatched_units
    intent.coverage_score = round(coverage, 3)
    intent.ambiguity = ambiguity
    return intent
