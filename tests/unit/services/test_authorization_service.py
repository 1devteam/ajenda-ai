import pytest

from backend.app.config import Settings
from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.policy import PolicyDecision
from backend.policy.opa_pdp import OpaPolicyDecisionPoint
from backend.services.authorization_service import AuthorizationService


def test_authorization_service_denies_missing_permission() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset())
    with pytest.raises(PermissionError):
        AuthorizationService().require(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")


class _AllowPdp:
    def authorize(self, **kwargs) -> PolicyDecision:  # type: ignore[no-untyped-def]
        return PolicyDecision(allowed=True, reason="ok", policy_source="test_allow")


class _DenyPdp:
    def authorize(self, **kwargs) -> PolicyDecision:  # type: ignore[no-untyped-def]
        return PolicyDecision(allowed=False, reason="denied_by_shadow", policy_source="test_shadow")


class _AuditRepo:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(event)


def test_authorization_service_records_shadow_divergence_event() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset())
    audit = _AuditRepo()
    service = AuthorizationService(
        audit_repository=audit,  # type: ignore[arg-type]
        policy_decision_point=_AllowPdp(),
        shadow_policy_decision_point=_DenyPdp(),
    )
    service.require(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.action == "shadow_decision"
    assert event.details == "shadow_policy_diverged"
    assert event.payload_json["shadow"]["policy_source"] == "test_shadow"


def test_from_settings_rbac_mode_uses_default_pdp() -> None:
    settings = Settings.model_construct(
        authz_policy_mode="rbac",
        authz_opa_url=None,
        authz_opa_timeout_seconds=2.0,
    )
    service = AuthorizationService.from_settings(settings)
    assert service._shadow_pdp is None  # type: ignore[attr-defined]


def test_from_settings_shadow_opa_mode_creates_shadow_pdp() -> None:
    settings = Settings.model_construct(
        authz_policy_mode="shadow_opa",
        authz_opa_url="http://opa:8181",
        authz_opa_timeout_seconds=1.5,
    )
    service = AuthorizationService.from_settings(settings)
    assert isinstance(service._shadow_pdp, OpaPolicyDecisionPoint)  # type: ignore[attr-defined]
