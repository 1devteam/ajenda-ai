from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.auth.permissions import Permission
from backend.auth.principal import Principal
from backend.auth.rbac import RbacAuthorizer


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    policy_source: str


class PolicyDecisionPoint(Protocol):
    """Policy decision point interface for authz evaluation.

    This abstraction allows plugging external policy engines (OPA/Cedar/etc.)
    without changing route/service call sites.
    """

    def authorize(self, *, principal: Principal, permission: Permission, tenant_id: str) -> PolicyDecision: ...


class RbacPolicyDecisionPoint:
    """Default in-process PDP backed by the existing RBAC authorizer."""

    def __init__(self) -> None:
        self._rbac = RbacAuthorizer()

    def authorize(self, *, principal: Principal, permission: Permission, tenant_id: str) -> PolicyDecision:
        decision = self._rbac.authorize(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
        )
        return PolicyDecision(
            allowed=decision.allowed,
            reason=decision.reason,
            policy_source="rbac",
        )
