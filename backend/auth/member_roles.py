"""Map tenant membership roles to RBAC role names."""

from __future__ import annotations

_MEMBER_TO_RBAC: dict[str, str] = {
    "tenant_owner": "tenant_admin",
    "tenant_admin": "tenant_admin",
    "operator": "operator",
    "viewer": "viewer",
}


def membership_role_to_rbac(member_role: str) -> str:
    """Return the RBAC role used for authorization decisions."""
    normalized = member_role.strip().lower()
    return _MEMBER_TO_RBAC.get(normalized, "viewer")
