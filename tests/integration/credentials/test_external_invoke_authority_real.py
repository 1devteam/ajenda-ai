"""Credentialed invoke paths without validate_capability_action_authority monkeypatch."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.workers.handlers.tool_invoke import tool_invoke_handler

from ._invoke_authority_helpers import seed_capability_adapter_authority, side_effect_authorization

pytestmark = pytest.mark.integration


def _store_hubspot_credential(session: Session, *, tenant_id: str, credential_id: str = "hubspot-crm") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-hubspot-pak")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_crm",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["sales.research", "crm.research", "gtm.crm_upsert"],
        allowed_side_effect_classes=["external_read", "external_write"],
        trusted_destination_hosts=["hubspot-crm-ingress"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def _store_gmail_credential(session: Session, *, tenant_id: str, credential_id: str = "gmail-email") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-gmail-bearer-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_email",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["gtm.email_send", "gtm.email_check"],
        allowed_side_effect_classes=["external_read", "external_send"],
        trusted_destination_hosts=["gmail.googleapis.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


@pytest.fixture
def hubspot_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST", "hubspot-crm-ingress")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS", "true")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_TLS_VERIFY", "false")
    from backend.app.config import get_settings

    get_settings.cache_clear()


def test_cross_tenant_credential_reference_denied_at_invoke(
    integration_env: None,
    hubspot_runtime_settings: None,
    pg_session: Session,
) -> None:
    owner_tenant = str(uuid.uuid4())
    attacker_tenant = str(uuid.uuid4())
    credential_id = _store_hubspot_credential(pg_session, tenant_id=owner_tenant)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=attacker_tenant,
        action_name="sales.research",
        side_effect_classification="external_read",
        extra_tools=("crm.research",),
    )
    pg_session.commit()

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=attacker_tenant,
        mission_id=uuid.uuid4(),
        title="cross tenant crm research",
        description="cross tenant crm research",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "sales.research",
                "input": {"lead": {"company": "Acme"}},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )

    with pytest.raises(Exception, match="credential denied.*not visible"):
        tool_invoke_handler(
            task,
            {
                "worker_id": "worker-test",
                "tenant_id": attacker_tenant,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: pg_session,
            },
        )


def test_sales_research_credentialed_invoke_without_capability_monkeypatch(
    integration_env: None,
    hubspot_runtime_settings: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_hubspot_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="sales.research",
        side_effect_classification="external_read",
        extra_tools=("crm.research",),
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://hubspot-crm-ingress/v1/search",
            connect_url="https://10.0.0.5/v1/search",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.5"),
            sni_hostname="hubspot-crm-ingress",
            host_header="hubspot-crm-ingress",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"results":[{"id":"330345792208"}],"count":1,"source":"hubspot"}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="crm research",
        description="crm research",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "sales.research",
                "input": {"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_read"
    assert result["output"]["plugin_required"] is True
    assert result["output"]["source"] == "hubspot"


def test_gmail_oauth_refresh_then_email_check_invoke_without_capability_monkeypatch(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    expired_at = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat()
    oauth_secret = json.dumps(
        {
            "access_token": "stale-access-token",
            "refresh_token": "refresh-token-abc",
            "expires_at": expired_at,
        }
    )
    protector = RuntimeCredentialSecretProtector()
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id="gmail-email",
        provider="external_email",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["gtm.email_send", "gtm.email_check"],
        allowed_side_effect_classes=["external_read", "external_send"],
        trusted_destination_hosts=["gmail.googleapis.com"],
        secret_ciphertext=protector.encrypt_secret(oauth_secret),
    )
    pg_session.add(row)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="gtm.email_check",
        side_effect_classification="external_read",
    )
    pg_session.commit()

    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "test-client-secret")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "fresh-access-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr("backend.services.tools.google_oauth_cli.httpx.Client", lambda **kwargs: fake_client)

    egress = MagicMock()
    egress.request.return_value = (
        VettedNetworkDestination(
            original_url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
            connect_url="https://10.0.0.6/gmail/v1/users/me/messages",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.6"),
            sni_hostname="gmail.googleapis.com",
            host_header="gmail.googleapis.com",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"messages":[{"id":"live-1","threadId":"t1","snippet":"Hello"}]}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        lambda: egress,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="gmail check",
        description="gmail check",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_check",
                "input": {"query": "is:unread", "limit": 5},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    fake_client.post.assert_called_once()
    assert egress.request.call_args.kwargs["headers"]["Authorization"] == "Bearer fresh-access-token"
    assert result["output"]["real"] is True
    assert result["output"]["emails"][0]["id"] == "live-1"
    assert result["output"]["emails"][0]["id"] != "sim-1"


def test_crm_upsert_credentialed_invoke_without_capability_monkeypatch(
    integration_env: None,
    hubspot_runtime_settings: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_hubspot_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="gtm.crm_upsert",
        side_effect_classification="external_write",
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://hubspot-crm-ingress/v1/upsert",
            connect_url="https://10.0.0.5/v1/upsert",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.5"),
            sni_hostname="hubspot-crm-ingress",
            host_header="hubspot-crm-ingress",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"id":"999","created":true,"record_type":"contact","source":"hubspot"}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="crm upsert",
        description="crm upsert",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.crm_upsert",
                "input": {
                    "record_type": "contact",
                    "data": {"email": "buyer@example.com", "firstname": "Jane"},
                },
                "idempotency_key": "upsert-auth-1",
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            **authority_refs,
            **side_effect_authorization(allowed_actions=["gtm.crm_upsert"]),
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_write"
    assert result["output"]["real"] is True
    assert result["output"]["status"] == "upserted_real"


def _store_linkedin_credential(session: Session, *, tenant_id: str, credential_id: str = "linkedin-read") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-linkedin-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["linkedin.profile_read", "provider.external_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["api.linkedin.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def _store_salesforce_credential(session: Session, *, tenant_id: str, credential_id: str = "salesforce-read") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-salesforce-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["salesforce.soql_read", "provider.external_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["acme.my.salesforce.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def test_linkedin_profile_read_invoke_without_capability_monkeypatch(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_linkedin_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="linkedin.profile_read",
        side_effect_classification="external_read",
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://api.linkedin.com/v2/me",
            connect_url="https://10.0.0.7/v2/me",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.7"),
            sni_hostname="api.linkedin.com",
            host_header="api.linkedin.com",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"id":"li-live-1","headline":{"localized":{"en_US":"Builder"}}}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.tools.linkedin_actions.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="linkedin profile read",
        description="linkedin profile read",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "linkedin.profile_read",
                "input": {},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_read_provider",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_read"
    assert result["output"]["real"] is True
    assert result["output"]["profile"]["id"] == "li-live-1"


def test_salesforce_soql_read_invoke_without_capability_monkeypatch(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_salesforce_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="salesforce.soql_read",
        side_effect_classification="external_read",
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://acme.my.salesforce.com/services/data/v59.0/query",
            connect_url="https://10.0.0.8/services/data/v59.0/query",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.8"),
            sni_hostname="acme.my.salesforce.com",
            host_header="acme.my.salesforce.com",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"totalSize":1,"done":true,"records":[{"Id":"001","Name":"Acme"}]}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.tools.salesforce_actions.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="salesforce soql read",
        description="salesforce soql read",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "salesforce.soql_read",
                "input": {"soql": "SELECT Id, Name FROM Account LIMIT 1"},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_read_provider",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_read"
    assert result["output"]["real"] is True
    assert result["output"]["result"]["records"][0]["Id"] == "001"


def _store_google_calendar_credential(
    session: Session, *, tenant_id: str, credential_id: str = "google-calendar-read"
) -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-google-calendar-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["google_calendar.events_read", "provider.external_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["www.googleapis.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def test_google_calendar_events_read_invoke_without_capability_monkeypatch(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_google_calendar_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="google_calendar.events_read",
        side_effect_classification="external_read",
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://www.googleapis.com/calendar/v3/calendars/primary/events",
            connect_url="https://10.0.0.9/calendar/v3/calendars/primary/events",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.9"),
            sni_hostname="www.googleapis.com",
            host_header="www.googleapis.com",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"items":[{"id":"evt-1","summary":"Planning"}]}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.tools.google_calendar_actions.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="google calendar events read",
        description="google calendar events read",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "google_calendar.events_read",
                "input": {"calendar_id": "primary", "limit": 5},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_read_provider",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_read"
    assert result["output"]["real"] is True
    assert result["output"]["events"][0]["id"] == "evt-1"


def _store_github_credential(session: Session, *, tenant_id: str, credential_id: str = "github-read") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-github-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["github.repo_read", "provider.external_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["api.github.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def test_github_repo_read_invoke_without_capability_monkeypatch(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    credential_id = _store_github_credential(pg_session, tenant_id=tenant_id)
    authority_refs = seed_capability_adapter_authority(
        pg_session,
        tenant_id=tenant_id,
        action_name="github.repo_read",
        side_effect_classification="external_read",
    )
    pg_session.commit()

    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://api.github.com/repos/ajenda/ajenda-ai",
            connect_url="https://10.0.0.10/repos/ajenda/ajenda-ai",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.10"),
            sni_hostname="api.github.com",
            host_header="api.github.com",
        ),
        NetworkEgressResponse(
            status_code=200,
            headers={},
            body_text='{"id":99,"full_name":"ajenda/ajenda-ai","private":false}',
            body_truncated=False,
        ),
    )
    monkeypatch.setattr(
        "backend.services.tools.github_actions.get_default_network_egress_authority",
        lambda: authority,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="github repo read",
        description="github repo read",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "github.repo_read",
                "input": {"owner": "ajenda", "repo": "ajenda-ai"},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": "external_read_provider",
                "credential_type": "api_key",
            },
            **authority_refs,
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )

    assert result["side_effect_class"] == "external_read"
    assert result["output"]["real"] is True
    assert result["output"]["repository"]["id"] == 99