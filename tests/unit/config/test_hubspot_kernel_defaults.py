"""HubSpot is an optional adapter. Kernel settings must not require it."""

from __future__ import annotations

import pytest

from backend.app.config import Settings


def test_hubspot_adapter_host_defaults_empty() -> None:
    field = Settings.model_fields["hubspot_crm_adapter_public_host"]
    assert field.default == ""


def test_hubspot_auto_provision_defaults_off() -> None:
    field = Settings.model_fields["hubspot_platform_master_auto_provision"]
    assert field.default is False


def test_hubspot_adapter_base_url_fails_closed_when_host_empty() -> None:
    settings = Settings.model_construct(hubspot_crm_adapter_public_host="")
    with pytest.raises(ValueError, match="not configured"):
        _ = settings.hubspot_crm_adapter_base_url


def test_hubspot_adapter_base_url_when_host_set() -> None:
    settings = Settings.model_construct(hubspot_crm_adapter_public_host="hubspot-crm-ingress")
    assert settings.hubspot_crm_adapter_base_url == "https://hubspot-crm-ingress"
