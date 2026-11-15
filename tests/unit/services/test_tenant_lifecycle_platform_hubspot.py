"""Unit tests for platform HubSpot auto-provision on tenant creation."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.app.config import Settings
from backend.domain.provision_source import ProvisionSource
from backend.services.tenant_lifecycle import TenantLifecycleService


def _tenant(*, slug: str = "acme") -> MagicMock:
    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.slug = slug
    tenant.plan = "free"
    tenant.status = "active"
    return tenant


def _settings(*, platform_master: bool, auto_provision: bool = True) -> Settings:
    return Settings.model_construct(
        env="test",
        hubspot_crm_adapter_public_host="hubspot-crm-ingress",
        hubspot_platform_master_key_enabled=platform_master,
        hubspot_platform_master_key="platform-test-key" if platform_master else None,
        hubspot_platform_master_auto_provision=auto_provision,
    )


@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_provision_auto_registers_platform_hubspot_credential(mock_mgmt_cls: MagicMock) -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    tenant = _tenant()
    repo.create.return_value = tenant
    mock_mgmt_cls.return_value.register.return_value = MagicMock()

    svc = TenantLifecycleService(session, settings=_settings(platform_master=True))
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
        credential_id="hubspot-crm",
        provider="external_crm",
        integration="hubspot",
        use_platform_master_key=True,
        platform_master_provisioned_by_operator=True,
        actor_id="system:admin",
    )


@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_provision_skips_hubspot_when_platform_master_disabled(mock_mgmt_cls: MagicMock) -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    tenant = _tenant(slug="no-hubspot")
    repo.create.return_value = tenant

    svc = TenantLifecycleService(session, settings=_settings(platform_master=False))
    svc._tenants = repo

    svc.provision(
        name="No HubSpot",
        slug="no-hubspot",
        plan="free",
        actor="admin",
        source=ProvisionSource.ADMIN,
    )

    mock_mgmt_cls.return_value.register.assert_not_called()


@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_provision_skips_hubspot_when_auto_provision_disabled(mock_mgmt_cls: MagicMock) -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    tenant = _tenant(slug="manual-only")
    repo.create.return_value = tenant

    svc = TenantLifecycleService(
        session,
        settings=_settings(platform_master=True, auto_provision=False),
    )
    svc._tenants = repo

    svc.provision(
        name="Manual Only",
        slug="manual-only",
        plan="free",
        actor="admin",
        source=ProvisionSource.ADMIN,
    )

    mock_mgmt_cls.return_value.register.assert_not_called()


@patch("backend.services.tenant_lifecycle.ProviderRuntimeCredentialRepository")
@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_reconcile_existing_tenant_requires_explicit_replacement(
    mock_mgmt_cls: MagicMock,
    mock_credentials_cls: MagicMock,
) -> None:
    session = MagicMock()
    tenant = _tenant()
    existing = MagicMock()
    existing.credential_type = "api_key"
    svc = TenantLifecycleService(session, settings=_settings(platform_master=True))
    svc._tenants = MagicMock()
    svc._tenants.get_active.return_value = tenant
    mock_credentials_cls.return_value.get_for_tenant.return_value = existing

    with pytest.raises(ValueError, match="replace_existing=true"):
        svc.reconcile_platform_hubspot_credential(tenant.id, actor="admin")

    mock_mgmt_cls.return_value.register.assert_not_called()


@patch("backend.services.tenant_lifecycle.ProviderRuntimeCredentialRepository")
@patch("backend.services.tenant_lifecycle.ProviderCredentialManagementService")
def test_reconcile_existing_tenant_replaces_credential_only_when_authorized(
    mock_mgmt_cls: MagicMock,
    mock_credentials_cls: MagicMock,
) -> None:
    session = MagicMock()
    tenant = _tenant()
    existing = MagicMock()
    existing.credential_type = "api_key"
    svc = TenantLifecycleService(session, settings=_settings(platform_master=True))
    svc._tenants = MagicMock()
    svc._tenants.get_active.return_value = tenant
    mock_credentials_cls.return_value.get_for_tenant.return_value = existing

    result = svc.reconcile_platform_hubspot_credential(
        tenant.id,
        actor="admin",
        replace_existing=True,
    )

    assert result.changed is True
    assert result.replaced_credential_type == "api_key"
    mock_mgmt_cls.return_value.register.assert_called_once_with(
        tenant_id=str(tenant.id),
        credential_id="hubspot-crm",
        provider="external_crm",
        integration="hubspot",
        use_platform_master_key=True,
        platform_master_provisioned_by_operator=True,
        actor_id="system:admin",
    )
    events = [call.args[0] for call in session.add.call_args_list]
    assert any(getattr(event, "event_type", None) == "tenant_platform_hubspot_reconciled" for event in events)


@patch("backend.services.tenant_lifecycle.ProviderRuntimeCredentialRepository")
def test_reconcile_platform_credential_is_idempotent(mock_credentials_cls: MagicMock) -> None:
    session = MagicMock()
    tenant = _tenant()
    existing = MagicMock()
    existing.credential_type = "platform_master"
    svc = TenantLifecycleService(session, settings=_settings(platform_master=True))
    svc._tenants = MagicMock()
    svc._tenants.get_active.return_value = tenant
    mock_credentials_cls.return_value.get_for_tenant.return_value = existing

    result = svc.reconcile_platform_hubspot_credential(tenant.id, actor="admin")

    assert result.changed is False
    assert result.replaced_credential_type is None
