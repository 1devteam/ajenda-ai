"""Outcome Intelligence Slice 1 — expected vs observed outcome assessment.

Answers: we expected X; reality became Y; did we make progress toward the
goal, by how much, and what does the evidence justify saying?

Distinct from Evaluation Intelligence:

- Evaluation asks: \"Where are we now relative to the goal?\"
- Outcome asks: \"What changed between baseline and observed result?\"

Reuses evaluate_kpi / compare_state_snapshots / evaluate_goal_progress.
Does not persist OutcomeReview, execute work, claim causation, or call an LLM.

Accuracy contracts (V1):
- No ACHIEVED when any required KPI lacks measurable data.
- No ACHIEVED when required evidence gaps are declared.
- State transitions are observed, never labeled \"desired\" without a contract.
- success_criteria_codes are recorded but not independently evaluated (opaque).
- KPI pairs must match metric/direction/goal_id or yield definition mismatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
    KpiDirection,
)
from backend.services.ontology.evaluation import (
    EvaluationResult,
    GapKind,
    GoalProgressStatus,
    ProgressGap,
    StateComparison,
    compare_state_snapshots,
    evaluate_goal_progress,
    evaluate_kpi,
)
from backend.services.ontology.types import BusinessObjectRef

OUTCOME_SCHEMA_VERSION = 1


class OutcomeStatus(StrEnum):
    """Conservative outcome assessment — no success claim without contract support."""

    ACHIEVED = \"achieved\"
    PARTIAL_PROGRESS = \"partial_progress\"
    NO_MATERIAL_CHANGE = \"no_material_change\"
    REGRESSED = \"regressed\"
    INCONCLUSIVE = \"inconclusive\"
    INSUFFICIENT_EVIDENCE = \"insufficient_evidence\"


class AttributionAssessment(StrEnum):
    """Explicit non-causal attribution of observed change to a prior decision/action."""

    NOT_ASSESSED = \"not_assessed\"
    TEMPORAL_ASSOCIATION = \"temporal_association\"
    SUPPORTED_CONTRIBUTION = \"supported_contribution\"
    CONFLICTING_EVIDENCE = \"conflicting_evidence\"
    INSUFFICIENT_EVIDENCE = \"insufficient_evidence\"


class DirectionAssessment(StrEnum):
    """Movement of a KPI relative to its target between baseline and observed."""

    TOWARD_TARGET = \"toward_target\"
    AWAY_FROM_TARGET = \"away_from_target\"
    UNCHANGED = \"unchanged\"
    TARGET_REACHED = \"target_reached\"
    INSUFFICIENT_DATA = \"insufficient_data\"
