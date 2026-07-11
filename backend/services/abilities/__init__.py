"""Ability rollout contract package."""

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION, INTERNAL_ABILITY_MANIFESTS
from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.abilities.role_contracts import (
    ARCHIVIST_ROLE_CONTRACT,
    COMMANDER_ROLE_CONTRACT,
    GUARDIAN_ROLE_CONTRACT,
    ROLE_CONTRACTS,
    RoleContract,
    RoleName,
    get_role_contract,
)
from backend.services.abilities.rollout_validation import (
    validate_action_manifest_alignment,
    validate_manifest,
    validate_manifest_collection,
)
from backend.services.abilities.vertical_role_catalog import (
    VERTICAL_OPS_PACK,
    VERTICAL_ROLE_SPECS_BY_KEY,
    RoleBindingStatus,
    VerticalRoleBinding,
    VerticalRolePack,
    VerticalRoleSpec,
    get_vertical_role,
    list_runtime_bound_action_names,
)

__all__ = [
    "ABILITY_MANIFESTS_BY_ACTION",
    "ARCHIVIST_ROLE_CONTRACT",
    "COMMANDER_ROLE_CONTRACT",
    "GUARDIAN_ROLE_CONTRACT",
    "INTERNAL_ABILITY_MANIFESTS",
    "ROLE_CONTRACTS",
    "VERTICAL_OPS_PACK",
    "VERTICAL_ROLE_SPECS_BY_KEY",
    "AbilityManifest",
    "AbilityRiskLevel",
    "RoleBindingStatus",
    "RoleContract",
    "RoleName",
    "VerticalRoleBinding",
    "VerticalRolePack",
    "VerticalRoleSpec",
    "get_role_contract",
    "get_vertical_role",
    "list_runtime_bound_action_names",
    "validate_action_manifest_alignment",
    "validate_manifest",
    "validate_manifest_collection",
]
