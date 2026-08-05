"""Fail-closed social publish infrastructure tests (IG/FB/YT/LinkedIn)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.services.tools.schemas import (
    ActionRuntimeContext,
    GtmSocialPublishInput,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.tools.social_publish import (
    FACEBOOK_TRUSTED_HOSTS,
    INSTAGRAM_TRUSTED_HOSTS,
    YOUTUBE_TRUSTED_HOSTS,
    build_social_publish_result,
    normalize_platform,
    trusted_hosts_for_platform,
)

_TASK_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_MISSION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _ctx(**kwargs: Any) -> ActionRuntimeContext:
    base = {
        "tenant_id": "tenant-1",
        "task_id": _TASK_ID,
        "mission_id": _MISSION_ID,
        "worker_id": "worker-1",
        "lease_id": "lease-1",
        "session_factory": None,
        "runtime_credentials": {},
    }
    base.update(kwargs)
    return ActionRuntimeContext(**base)  # type: ignore[arg-type]


def _inv(**kwargs: Any) -> ToolInvocation:
    base = {
        "action": "gtm.social_publish",
        "input": {},
        "idempotency_key": "idem-1",
    }
    base.update(kwargs)
    return ToolInvocation(**base)  # type: ignore[arg-type]


def _make_evidence(*args: Any, **kwargs: Any) -> Any:
    from backend.services.tools.gtm_actions import _make_evidence

    return _make_evidence(*args, **kwargs)


def test_normalize_platform_aliases() -> None:
    assert normalize_platform("IG") == "instagram"
    assert normalize_platform("fb") == "facebook"
    assert normalize_platform("yt") == "youtube"
    assert trusted_hosts_for_platform("instagram") == INSTAGRAM_TRUSTED_HOSTS
    assert trusted_hosts_for_platform("facebook") == FACEBOOK_TRUSTED_HOSTS
    assert trusted_hosts_for_platform("youtube") == YOUTUBE_TRUSTED_HOSTS


def test_missing_credential_fails_closed_without_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)
    monkeypatch.setenv("AJENDA_ENV", "production")
    result = build_social_publish_result(
        inv=_inv(),
        ctx=_ctx(),
        inp=GtmSocialPublishInput(
            platform="facebook",
            content="Hello world",
            context={"page_id": "123"},
        ),
        social_cred=None,
        make_evidence=_make_evidence,
    )
    assert result.side_effect_class == SideEffectClass.EXTERNAL_PUBLISH
    assert result.output["real"] is False
    assert result.output["status"] == "error"
    assert "credential" in (result.output.get("error") or "").lower()
    assert result.evidence


def test_unsupported_platform_fails_closed() -> None:
    result = build_social_publish_result(
        inv=_inv(),
        ctx=_ctx(),
        inp=GtmSocialPublishInput(platform="twitter", content="hi"),
        social_cred=SimpleNamespace(secret_value="token", trusted_destination_hosts=["graph.facebook.com"]),
        make_evidence=_make_evidence,
    )
    assert result.output["real"] is False
    assert result.output["status"] == "error"
    assert "unsupported" in (result.output.get("error") or "")


def test_missing_idempotency_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)
    result = build_social_publish_result(
        inv=_inv(idempotency_key=None),
        ctx=_ctx(session_factory=lambda: MagicMock()),
        inp=GtmSocialPublishInput(
            platform="facebook",
            content="Hello",
            context={"page_id": "page-1"},
        ),
        social_cred=SimpleNamespace(
            secret_value="token",
            trusted_destination_hosts=list(FACEBOOK_TRUSTED_HOSTS),
        ),
        make_evidence=_make_evidence,
    )
    assert result.output["real"] is False
    assert result.output["status"] == "error"
    assert "idempotency" in (result.output.get("error") or "").lower()


def test_facebook_publish_success_records_evidence_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)
    claims: list[str] = []
    completes: list[dict[str, Any]] = []

    def fake_claim(**kwargs: Any) -> Any:
        claims.append(kwargs["idempotency_key"])
        return SimpleNamespace(decision="newly_claimed", idempotency_key=kwargs["idempotency_key"], error=None)

    def fake_complete(**kwargs: Any) -> None:
        completes.append(kwargs["result_payload"])

    class FakeResp:
        status_code = 200
        body_text = '{"id":"123_456"}'
        headers: dict[str, str] = {}

    with (
        patch("backend.services.tools.social_publish.claim_smtp_send", side_effect=fake_claim),
        patch("backend.services.tools.social_publish.complete_smtp_send", side_effect=fake_complete),
        patch("backend.services.tools.social_publish.release_smtp_send"),
        patch(
            "backend.services.tools.social_publish.get_default_network_egress_authority"
        ) as egress,
    ):
        egress.return_value.request.return_value = ("graph.facebook.com", FakeResp())
        result = build_social_publish_result(
            inv=_inv(idempotency_key="pub-key-1"),
            ctx=_ctx(session_factory=lambda: MagicMock()),
            inp=GtmSocialPublishInput(
                platform="facebook",
                content="Roofing tip of the week",
                context={"page_id": "page-9"},
            ),
            social_cred=SimpleNamespace(
                secret_value="page-token",
                trusted_destination_hosts=list(FACEBOOK_TRUSTED_HOSTS),
            ),
            make_evidence=_make_evidence,
        )

    assert result.output["real"] is True
    assert result.output["status"] == "published"
    assert result.output["provider_post_id"] == "123_456"
    assert result.output["idempotency_key"] == "pub-key-1"
    assert claims == ["pub-key-1"]
    assert completes and completes[0]["provider_post_id"] == "123_456"
    evidence = result.evidence[0]
    assert evidence.structured_payload["provider_post_id"] == "123_456"
    assert evidence.structured_payload["tenant_id"] == "tenant-1"


def test_instagram_requires_media_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)

    def fake_claim(**kwargs: Any) -> Any:
        return SimpleNamespace(decision="newly_claimed", idempotency_key=kwargs["idempotency_key"], error=None)

    with (
        patch("backend.services.tools.social_publish.claim_smtp_send", side_effect=fake_claim),
        patch("backend.services.tools.social_publish.release_smtp_send") as release,
        patch("backend.services.tools.social_publish.complete_smtp_send"),
    ):
        result = build_social_publish_result(
            inv=_inv(idempotency_key="ig-1"),
            ctx=_ctx(session_factory=lambda: MagicMock()),
            inp=GtmSocialPublishInput(
                platform="instagram",
                content="caption",
                context={"ig_user_id": "ig-1"},
            ),
            social_cred=SimpleNamespace(
                secret_value="token",
                trusted_destination_hosts=list(INSTAGRAM_TRUSTED_HOSTS),
            ),
            make_evidence=_make_evidence,
        )
    assert result.output["real"] is False
    assert "media_url" in (result.output.get("error") or "")
    release.assert_called()


def test_youtube_requires_media_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)

    def fake_claim(**kwargs: Any) -> Any:
        return SimpleNamespace(decision="newly_claimed", idempotency_key=kwargs["idempotency_key"], error=None)

    with (
        patch("backend.services.tools.social_publish.claim_smtp_send", side_effect=fake_claim),
        patch("backend.services.tools.social_publish.release_smtp_send"),
        patch("backend.services.tools.social_publish.complete_smtp_send"),
    ):
        result = build_social_publish_result(
            inv=_inv(idempotency_key="yt-1"),
            ctx=_ctx(session_factory=lambda: MagicMock()),
            inp=GtmSocialPublishInput(
                platform="youtube",
                content="video description",
                title="My video",
            ),
            social_cred=SimpleNamespace(
                secret_value="token",
                trusted_destination_hosts=list(YOUTUBE_TRUSTED_HOSTS),
            ),
            make_evidence=_make_evidence,
        )
    assert result.output["real"] is False
    assert "media_url" in (result.output.get("error") or "")


def test_idempotent_replay_returns_cached_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)
    cached = {
        "platform": "facebook",
        "status": "published",
        "real": True,
        "provider_post_id": "cached-1",
        "content": "Hello",
    }

    def fake_claim(**kwargs: Any) -> Any:
        return SimpleNamespace(
            decision="replayed",
            idempotency_key=kwargs["idempotency_key"],
            cached_output=cached,
            error=None,
        )

    with patch("backend.services.tools.social_publish.claim_smtp_send", side_effect=fake_claim):
        result = build_social_publish_result(
            inv=_inv(idempotency_key="replay-1"),
            ctx=_ctx(session_factory=lambda: MagicMock()),
            inp=GtmSocialPublishInput(
                platform="facebook",
                content="Hello",
                context={"page_id": "p"},
            ),
            social_cred=SimpleNamespace(
                secret_value="token",
                trusted_destination_hosts=list(FACEBOOK_TRUSTED_HOSTS),
            ),
            make_evidence=_make_evidence,
        )
    assert result.output["idempotency_replayed"] is True
    assert result.output["provider_post_id"] == "cached-1"
    assert result.output["real"] is True


def test_external_social_provider_registration_scope() -> None:
    from backend.services.credentials.management_service import ProviderCredentialManagementService

    svc = ProviderCredentialManagementService(session=MagicMock())
    actions, side_effects, hosts = svc._default_scope(
        provider="external_social",
        integration="instagram",
        secret_value="tok",
        allowed_actions=None,
        allowed_side_effect_classes=None,
        trusted_destination_hosts=None,
    )
    assert "gtm.social_publish" in actions
    assert "external_publish" in side_effects
    assert "graph.facebook.com" in hosts or "graph.instagram.com" in hosts
