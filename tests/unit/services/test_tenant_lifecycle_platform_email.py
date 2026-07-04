"""Unit tests for platform email auto-provision on tenant creation."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.app.config import Settings
from backend.domain.provision_source import ProvisionSource
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.tenant_lifecycle import TenantLifecycleService


def _tenant(*, slug: str = "acme") -> MagicMock:
    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.slug = slug
    tenant.plan = "free"
    tenant.status = "active"
    return tenant


def _settings(*, email_platform: bool, auto_provision: bool = True) -> Settings:
    smtp_secret = (
        '{"host":"smtp.example.com","port":587,"user":"send@ajenda.ai","password":"secret","from":"send@ajenda.ai"}'
        if email_platform
        else None
    )
    return Settings.model_construct(
        env="test",
        hubspot_crm_adapter_public_host="hubspot-crm-ingress",
        hubspot_platform_master_key_enabled=False,
        hubspot_platform_master_key=None,
        hubspot_platform_master_auto_provision=False,
        email_platform_master_key_enabled=email_platform,
        email_platform_smtp_secret=smtp_secret,
        email_platform_master_auto_provision=auto_provision,
        runtime_secret_encryption_key=RuntimeCredentialSecretProtector().generate_key(),
    )


@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_provision_auto_registers_platform_email_credential(mock_mgmt_cls: MagicMock) -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    tenant = _tenant()
    repo.create.return_value = tenant
    mock_mgmt_cls.return_value.register.return_value = MagicMock()

    svc = TenantLifecycleService(session, settings=_settings(email_platform=True))
    svc._tenants = repo

    result = svc.provision(
        name="Acme",
        slug="acme",
        plan="free",
        actor="admin",
        source=ProvisionSource.ADMIN,
    )

    assert result.slug == "acme"
    mock_mgmt_cls.return_value.register.assert_called_once_with(
        tenant_id=str(tenant.id),
        credential_id="ajenda-email",
        provider="external_email",
        integration="smtp",
        use_platform_master_key=True,
        actor_id="system:admin",
    )


@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_provision_skips_email_when_platform_lane_disabled(mock_mgmt_cls: MagicMock) -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    tenant = _tenant(slug="no-email")
    repo.create.return_value = tenant

    svc = TenantLifecycleService(session, settings=_settings(email_platform=False))
    svc._tenants = repo

    svc.provision(
        name="No Email",
        slug="no-email",
        plan="free",
        actor="admin",
        source=ProvisionSource.ADMIN,
    )

    mock_mgmt_cls.return_value.register.assert_not_called()
