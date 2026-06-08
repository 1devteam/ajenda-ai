"""Validation helpers for ability rollout manifests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from backend.services.abilities.manifest import AbilityManifest
from backend.services.tools.action_registry import ActionDefinition
from backend.services.tools.schemas import SideEffectClass


def validate_manifest(manifest: AbilityManifest) -> AbilityManifest:
    """Return the manifest after Pydantic and policy validation."""

    return AbilityManifest.model_validate(manifest.model_dump(mode="json"))


def validate_action_manifest_alignment(
    *,
    action_definition: ActionDefinition,
    manifest: AbilityManifest,
) -> None:
    """Validate that a manifest matches a registered action definition."""

    if manifest.action_name != action_definition.name:
        raise ValueError("ability manifest action_name must match registered action name")
    if manifest.provider != action_definition.provider:
        raise ValueError("ability manifest provider must match registered action provider")
    if action_definition.side_effect_resolver is None:
        if manifest.side_effect_class != action_definition.side_effect_class:
            raise ValueError("ability manifest side_effect_class must match registered action side_effect_class")
    else:
        if manifest.max_side_effect_class is None:
            raise ValueError("resolver-backed actions require max_side_effect_class")
        if manifest.side_effect_class != action_definition.side_effect_class:
            raise ValueError(
                "ability manifest side_effect_class must match registered action default side_effect_class"
            )
        if _side_effect_rank(manifest.max_side_effect_class) < _side_effect_rank(action_definition.side_effect_class):
            raise ValueError("ability manifest max_side_effect_class cannot be lower than registered default")
    if tuple(manifest.required_permissions) != tuple(action_definition.required_permissions):
        raise ValueError("ability manifest required_permissions must match registered action permissions")
    if tuple(manifest.required_tools) != tuple(action_definition.required_tools):
        raise ValueError("ability manifest required_tools must match registered action tools")


def validate_manifest_collection(
    *,
    manifests: Iterable[AbilityManifest],
    registered_actions: Mapping[str, ActionDefinition],
    require_all_registered: bool = False,
) -> None:
    """Validate a manifest collection against registered actions.

    When require_all_registered is false, this helper validates only supplied
    manifests. When true, every canonical registered action name must have one
    manifest. Aliases are ignored by requiring each ActionDefinition.name once.
    """

    manifest_by_action: dict[str, AbilityManifest] = {}
    for manifest in manifests:
        if manifest.action_name in manifest_by_action:
            raise ValueError(f"duplicate ability manifest for action {manifest.action_name!r}")
        action_definition = registered_actions.get(manifest.action_name)
        if action_definition is None:
            raise ValueError(f"ability manifest references unknown action {manifest.action_name!r}")
        validate_action_manifest_alignment(action_definition=action_definition, manifest=manifest)
        manifest_by_action[manifest.action_name] = manifest

    if require_all_registered:
        canonical_actions = {definition.name for definition in registered_actions.values()}
        missing = sorted(canonical_actions - set(manifest_by_action))
        if missing:
            raise ValueError(f"missing ability manifests for registered actions: {missing}")


_SIDE_EFFECT_RANK = {
    SideEffectClass.NONE: 0,
    SideEffectClass.INTERNAL_READ: 1,
    SideEffectClass.EXTERNAL_READ: 2,
    SideEffectClass.INTERNAL_WRITE: 3,
    SideEffectClass.EXTERNAL_WRITE: 4,
    SideEffectClass.EXTERNAL_SEND: 5,
    SideEffectClass.EXTERNAL_PUBLISH: 6,
}


def _side_effect_rank(side_effect_class: SideEffectClass) -> int:
    return _SIDE_EFFECT_RANK[side_effect_class]
