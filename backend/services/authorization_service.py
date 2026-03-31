from __future__ import annotations

from backend.auth.permissions import Permission
from backend.auth.principal import Principal
from backend.auth.rbac import RbacAuthorizer
from backend.domain.audit_event import AuditEvent
from backend.repositories.audit_event_repository import AuditEventRepository


class AuthorizationService:
    def __init__(self, audit_repository: AuditEventRepository | None = None) -> None:
        self._authorizer = RbacAuthorizer()
        self._audit = audit_repository

    def require(self, *, principal: Principal, permission: Permission, tenant_id: str) -> None:
        decision = self._authorizer.authorize(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
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
                        payload_json={"permission": permission.value},
                    )
                )
            raise PermissionError(decision.reason)
