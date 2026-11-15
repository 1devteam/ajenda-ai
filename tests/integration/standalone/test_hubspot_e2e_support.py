from __future__ import annotations

from tests.integration.standalone.hubspot_e2e_support import resolve_hubspot_access_token


def test_hubspot_e2e_uses_only_explicit_crm_access_token(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_E2E_HUBSPOT_PAK", "cli-personal-access-key")
    monkeypatch.delenv("AJENDA_E2E_HUBSPOT_CRM_TOKEN", raising=False)

    assert resolve_hubspot_access_token() is None

    monkeypatch.setenv("AJENDA_E2E_HUBSPOT_CRM_TOKEN", "crm-service-key")

    assert resolve_hubspot_access_token() == "crm-service-key"
