"""GitHub OAuth refresh through SQLAlchemy credential repository."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.github_oauth_client import GITHUB_OAUTH_TOKEN_URL
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.credentials.sqlalchemy_repository import SQLAlchemyCredentialRuntimeRepository

pytestmark = pytest.mark.integration


def _store_expired_github_oauth_credential(
    session: Session,
    *,
    tenant_id: str,
    credential_id: str = "github-read",
) -> str:
    expired_at = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat()
    secret = json.dumps(
        {
            "provider_kind": "github",
            "access_token": "stale-access-token",
            "refresh_token": "refresh-token-abc",
            "expires_at": expired_at,
        }
    )
    protector = RuntimeCredentialSecretProtector()
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
        secret_ciphertext=protector.encrypt_secret(secret),
    )
    session.add(row)
    session.flush()
    return secret


def test_expired_github_oauth_secret_refreshes_via_httpx_and_persists_ciphertext(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    original_secret = _store_expired_github_oauth_credential(pg_session, tenant_id=tenant_id)
    pg_session.commit()

    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_SECRET", "test-client-secret")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "fresh-access-token",
                "expires_in": 3600,
                "token_type": "bearer",
                "scope": "read:user",
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()

    monkeypatch.setattr("backend.services.credentials.github_oauth_client.httpx.Client", lambda **kwargs: fake_client)

    repository = SQLAlchemyCredentialRuntimeRepository(session_factory=lambda: pg_session)
    record = repository.get_visible_for_tenant(tenant_id=tenant_id, credential_id="github-read")

    assert record is not None
    assert record.secret_value == "fresh-access-token"
    fake_client.post.assert_called_once()
    assert fake_client.post.call_args.args[0] == GITHUB_OAUTH_TOKEN_URL

    row = pg_session.execute(
        select(ProviderRuntimeCredential).where(
            ProviderRuntimeCredential.tenant_id == tenant_id,
            ProviderRuntimeCredential.credential_id == "github-read",
        )
    ).scalar_one()
    protector = RuntimeCredentialSecretProtector()
    persisted = protector.decrypt_secret(row.secret_ciphertext)
    assert persisted != original_secret
    assert json.loads(persisted)["access_token"] == "fresh-access-token"
