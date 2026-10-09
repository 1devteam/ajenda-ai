"""Derive non-empty tool.invoke inputs from MissionIntent for composed graphs.

Provider/action-family implementations are deliberately split by responsibility.
This module remains the stable public import and graph boundary.
"""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.action_input_analysis import build_analysis_action_input
from backend.services.mission_composition.action_input_common import (
    _target_bits,
    extract_github_owner_repo as _extract_github_owner_repo,
    has_usable_research_scope as _has_usable_research_scope,
)
from backend.services.mission_composition.action_input_communications import build_communications_action_input
from backend.services.mission_composition.action_input_provider_reads import build_provider_read_action_input
from backend.services.mission_composition.action_input_research import build_research_action_input
from backend.services.mission_composition.action_input_sales import build_sales_action_input
from backend.services.mission_composition.contracts import MissionIntent


def has_usable_research_scope(intent: MissionIntent) -> bool:
    """Preserve the canonical research-scope compatibility boundary."""

    return _has_usable_research_scope(intent)


def extract_github_owner_repo(intent: MissionIntent) -> tuple[str, str] | None:
    """Preserve the canonical explicit GitHub target compatibility boundary."""

    return _extract_github_owner_repo(intent)


def build_action_input(
    *, action_name: str, intent: MissionIntent, vertical_role: str | None = None
) -> dict[str, Any]:
    """Return a schema-valid-enough input payload for the selected action."""

    payload = build_research_action_input(action_name=action_name, intent=intent)
    if payload is not None:
        return payload

    payload = build_analysis_action_input(action_name=action_name, intent=intent)
    if payload is not None:
        return payload

    payload = build_sales_action_input(action_name=action_name, intent=intent, vertical_role=vertical_role)
    if payload is not None:
        return payload

    payload = build_communications_action_input(action_name=action_name, intent=intent)
    if payload is not None:
        return payload

    payload = build_provider_read_action_input(action_name=action_name, intent=intent)
    if payload is not None:
        return payload

    _, _, query = _target_bits(intent)
    return {"context": {"objective": intent.objective[:300], "query": query}}
