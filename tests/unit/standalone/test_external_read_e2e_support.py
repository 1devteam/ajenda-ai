from __future__ import annotations

import json

import pytest

from tests.integration.standalone.linkedin_e2e_support import resolve_linkedin_credential_secret_for_e2e
from tests.integration.standalone.salesforce_e2e_support import resolve_salesforce_credential_secret_for_e2e


def test_resolve_linkedin_secret_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_E2E_LINKEDIN_TOKEN", "linkedin-bearer-token")
    assert resolve_linkedin_credential_secret_for_e2e() == "linkedin-bearer-token"


def test_resolve_salesforce_secret_from_token_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_E2E_SALESFORCE_SECRET", raising=False)
    monkeypatch.setenv("AJENDA_E2E_SALESFORCE_TOKEN", "sf-access")
    monkeypatch.setenv("AJENDA_E2E_SALESFORCE_INSTANCE_HOST", "Acme.My.Salesforce.com")
    secret = resolve_salesforce_credential_secret_for_e2e()
    assert secret is not None
    payload = json.loads(secret)
    assert payload["access_token"] == "sf-access"
    assert payload["instance_url"] == "https://acme.my.salesforce.com"