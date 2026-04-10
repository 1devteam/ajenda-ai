from __future__ import annotations

from backend.app.config import Settings
from backend.auth.permissions import Permission
from backend.auth.principal import Principal
from backend.domain.audit_event import AuditEvent
from backend.policy import OpaPolicyDecisionPoint, PolicyDecisionPoint, RbacPolicyDecisionPoint
from backend.repositories.audit_event_repository import AuditEventRepository


class AuthorizationService:
    def __init__(
        self,
        audit_repository: AuditEventRepository | None = None,
        *,
        policy_decision_point: PolicyDecisionPoint | None = None,
        shadow_policy_decision_point: PolicyDecisionPoint | None = None,
    ) -> None:
        self._pdp = policy_decision_point or RbacPolicyDecisionPoint()
        self._shadow_pdp = shadow_policy_decision_point
        self._audit = audit_repository

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        audit_repository: AuditEventRepository | None = None,
    ) -> AuthorizationService:
        """Build authz service based on configured policy mode."""
        if settings.authz_policy_mode == "rbac":
            return cls(audit_repository=audit_repository)

        opa_pdp = OpaPolicyDecisionPoint(
            base_url=str(settings.authz_opa_url),
            timeout_seconds=settings.authz_opa_timeout_seconds,
        )
        if settings.authz_policy_mode == "shadow_opa":
            return cls(
                audit_repository=audit_repository,
                policy_decision_point=RbacPolicyDecisionPoint(),
                shadow_policy_decision_point=opa_pdp,
            )

        return cls(
            audit_repository=audit_repository,
            policy_decision_point=opa_pdp,
        )

    def require(self, *, principal: Principal, permission: Permission, tenant_id: str) -> None:
        decision = self._pdp.authorize(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
        )
        self._record_shadow_decision(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
            enforced_allowed=decision.allowed,
            enforced_reason=decision.reason,
            enforced_source=decision.policy_source,
        )
        if not decision.allowed:
            if self._audit is not None:
                self._audit.append(
                    AuditEvent(
                        tenant_id=tenant_id,
                        mission_id=None,
                        category="authz",
                        action="denied",
                        actor=principal.subject_id,
                        details=decision.reason,
                        payload_json={"permission": permission.value, "policy_source": decision.policy_source},
                    )
                )
            raise PermissionError(decision.reason)

    def _record_shadow_decision(
        self,
        *,
        principal: Principal,
        permission: Permission,
        tenant_id: str,
        enforced_allowed: bool,
        enforced_reason: str,
        enforced_source: str,
    ) -> None:
        if self._shadow_pdp is None or self._audit is None:
            return
        shadow = self._shadow_pdp.authorize(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
        )
        diverged = shadow.allowed != enforced_allowed
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=None,
                category="authz",
                action="shadow_decision",
                actor=principal.subject_id,
                details=(
                    "shadow_policy_diverged" if diverged else "shadow_policy_aligned"
                ),
                payload_json={
                    "permission": permission.value,
                    "enforced": {
                        "allowed": enforced_allowed,
                        "reason": enforced_reason,
                        "policy_source": enforced_source,
                    },
                    "shadow": {
                        "allowed": shadow.allowed,
                        "reason": shadow.reason,
                        "policy_source": shadow.policy_source,
                    },
                },
            )
        )
