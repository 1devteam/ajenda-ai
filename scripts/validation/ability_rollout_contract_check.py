"""Validate AbilityManifest catalog alignment with registered tool actions."""

from __future__ import annotations

from backend.services.abilities.catalog import INTERNAL_ABILITY_MANIFESTS
from backend.services.abilities.rollout_validation import validate_manifest_collection
from backend.services.tools.action_registry import get_default_action_registry


def main() -> int:
    registry = get_default_action_registry(rebuild=True)
    validate_manifest_collection(
        manifests=INTERNAL_ABILITY_MANIFESTS,
        registered_actions=registry.actions,
        require_all_registered=True,
    )
    print("PASS: ability rollout contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
