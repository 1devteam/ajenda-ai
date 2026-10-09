"""Stable action-input composition boundary.

The provider/action-family implementation lives in action_input_engine.
Keep this module as the canonical import and patch surface for composition,
capability resolution, tests, and graph identity.
"""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.action_input_engine import (
    build_action_input as _build_action_input,
)
from backend.services.mission_composition.action_input_engine import (
    extract_github_owner_repo as _extract_github_owner_repo,
)
from backend.services.mission_composition.action_input_engine import (
    has_usable_research_scope as _has_usable_research_scope,
)
from backend.services.mission_composition.contracts import MissionIntent


def has_usable_research_scope(intent: MissionIntent) -> bool:
    """Return whether intent carries a provider-safe research scope."""

    return _has_usable_research_scope(intent)


def extract_github_owner_repo(intent: MissionIntent) -> tuple[str, str] | None:
    """Extract an explicit GitHub owner/repository target without inventing one."""

    return _extract_github_owner_repo(intent)


def build_action_input(
    *,
    action_name: str,
    intent: MissionIntent,
    vertical_role: str | None = None,
) -> dict[str, Any]:
    """Build a schema-valid action input through the implementation engine."""

    return _build_action_input(
        action_name=action_name,
        intent=intent,
        vertical_role=vertical_role,
    )
