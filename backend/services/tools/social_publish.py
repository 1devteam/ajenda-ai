"""Platform social publish adapters for Instagram, Facebook, YouTube, and LinkedIn.

Infrastructure only: handlers execute under ActionRegistry / TaskDispatcher.
Credentials stay in the encrypted credential store. Network egress is always
vetted through NetworkEgressAuthority. Missing credentials and missing
idempotency keys fail closed — never silent simulated success in production.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlencode

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.email_send_idempotency import (
    claim_smtp_send,
    complete_smtp_send,
    release_smtp_send,
)
from backend.services.tools.external_sim_policy import allow_simulated_external, require_external_secret
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    GtmSocialPublishInput,
    SideEffectClass,
    ToolInvocation,
)

SocialPlatform = Literal["instagram", "facebook", "youtube", "linkedin"]

SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"instagram", "facebook", "youtube", "linkedin"})

# Declarative trusted hosts for credential registration + egress allowlists.
INSTAGRAM_TRUSTED_HOSTS: tuple[str, ...] = ("graph.facebook.com", "graph.instagram.com")
FACEBOOK_TRUSTED_HOSTS: tuple[str, ...] = ("graph.facebook.com",)
YOUTUBE_TRUSTED_HOSTS: tuple[str, ...] = ("www.googleapis.com", "youtube.googleapis.com")
LINKEDIN_PUBLISH_TRUSTED_HOSTS: tuple[str, ...] = ("api.linkedin.com",)

SOCIAL_PUBLISH_ACTIONS: tuple[str, ...] = ("gtm.social_publish",)
SOCIAL_PUBLISH_SIDE_EFFECTS: tuple[str, ...] = ("external_publish",)

GRAPH_API_VERSION = "v21.0"


@dataclass(frozen=True, slots=True)
class SocialPublishAttempt:
    status: str
    real: bool
    platform: str
    provider_post_id: str | None = None
    destination_url: str | None = None
    error: str | None = None
    http_status: int | None = None
    body_preview: str | None = None
    reason: str | None = None


def normalize_platform(raw: str) -> str:
    value = (raw or "").strip().casefold().replace(" ", "_")
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "fb": "facebook",
        "meta": "facebook",
        "yt": "youtube",
        "google_youtube": "youtube",
        "li": "linkedin",
    }
    return aliases.get(value, value)


def trusted_hosts_for_platform(platform: str) -> tuple[str, ...]:
    mapping = {
        "instagram": INSTAGRAM_TRUSTED_HOSTS,
        "facebook": FACEBOOK_TRUSTED_HOSTS,
        "youtube": YOUTUBE_TRUSTED_HOSTS,
        "linkedin": LINKEDIN_PUBLISH_TRUSTED_HOSTS,
    }
    return mapping.get(platform, ())


def _http_is_success(status_code: int) -> bool:
    return 200 <= status_code < 300


def _destination_id(inp: GtmSocialPublishInput) -> str:
    context = inp.context if isinstance(inp.context, dict) else {}
    for key in (
        "destination_id",
        "page_id",
        "ig_user_id",
        "instagram_user_id",
        "channel_id",
        "author_urn",
        "person_urn",
    ):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _media_url(inp: GtmSocialPublishInput) -> str:
    context = inp.context if isinstance(inp.context, dict) else {}
    for key in ("media_url", "image_url", "video_url"):
        value = context.get(key)
        if isinstance(value, str) and value.strip().startswith("https://"):
            return value.strip()
    if isinstance(inp.media_url, str) and inp.media_url.strip().startswith("https://"):
        return inp.media_url.strip()
    return ""


def _title(inp: GtmSocialPublishInput) -> str:
    if isinstance(inp.title, str) and inp.title.strip():
        return inp.title.strip()
    context = inp.context if isinstance(inp.context, dict) else {}
    value = context.get("title")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _parse_json_body(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def publish_facebook_page(
    *,
    secret: str,
    page_id: str,
    message: str,
    trusted_hosts: tuple[str, ...],
    action_name: str,
    idempotency_key: str | None,
) -> SocialPublishAttempt:
    host = trusted_hosts[0] if trusted_hosts else FACEBOOK_TRUSTED_HOSTS[0]
    path = f"/{GRAPH_API_VERSION}/{quote(page_id, safe='')}/feed"
    url = f"https://{host}{path}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    body = {"message": message, "access_token": secret}
    _dest, resp = get_default_network_egress_authority().request(
        method="POST",
        url=url,
        headers=headers,
        json_body=body,
        allowed_hosts=list(trusted_hosts or FACEBOOK_TRUSTED_HOSTS),
        action_name=action_name,
        timeout_seconds=20.0,
    )
    parsed = _parse_json_body(resp.body_text)
    if _http_is_success(resp.status_code) and parsed.get("id"):
        post_id = str(parsed["id"])
        return SocialPublishAttempt(
            status="published",
            real=True,
            platform="facebook",
            provider_post_id=post_id,
            destination_url=f"https://www.facebook.com/{post_id}",
            http_status=resp.status_code,
            body_preview=(resp.body_text or "")[:300],
        )
    return SocialPublishAttempt(
        status="error",
        real=False,
        platform="facebook",
        error=f"Facebook Graph feed publish failed HTTP {resp.status_code}",
        http_status=resp.status_code,
        body_preview=(resp.body_text or "")[:300],
    )


def publish_instagram(
    *,
    secret: str,
    ig_user_id: str,
    caption: str,
    image_url: str,
    trusted_hosts: tuple[str, ...],
    action_name: str,
    idempotency_key: str | None,
) -> SocialPublishAttempt:
    if not image_url:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="instagram",
            error="instagram_publish_requires_https_media_url",
            reason="media_url_required",
        )
    host = trusted_hosts[0] if trusted_hosts else INSTAGRAM_TRUSTED_HOSTS[0]
    allowed = list(trusted_hosts or INSTAGRAM_TRUSTED_HOSTS)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    create_url = f"https://{host}/{GRAPH_API_VERSION}/{quote(ig_user_id, safe='')}/media"
    _dest, create_resp = get_default_network_egress_authority().request(
        method="POST",
        url=create_url,
        headers=headers,
        json_body={"image_url": image_url, "caption": caption, "access_token": secret},
        allowed_hosts=allowed,
        action_name=action_name,
        timeout_seconds=30.0,
    )
    create_payload = _parse_json_body(create_resp.body_text)
    creation_id = create_payload.get("id")
    if not _http_is_success(create_resp.status_code) or not creation_id:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="instagram",
            error=f"Instagram media container create failed HTTP {create_resp.status_code}",
            http_status=create_resp.status_code,
            body_preview=(create_resp.body_text or "")[:300],
        )

    publish_url = f"https://{host}/{GRAPH_API_VERSION}/{quote(ig_user_id, safe='')}/media_publish"
    _dest, publish_resp = get_default_network_egress_authority().request(
        method="POST",
        url=publish_url,
        headers=headers,
        json_body={"creation_id": str(creation_id), "access_token": secret},
        allowed_hosts=allowed,
        action_name=action_name,
        timeout_seconds=30.0,
    )
    publish_payload = _parse_json_body(publish_resp.body_text)
    media_id = publish_payload.get("id")
    if _http_is_success(publish_resp.status_code) and media_id:
        return SocialPublishAttempt(
            status="published",
            real=True,
            platform="instagram",
            provider_post_id=str(media_id),
            destination_url=f"https://www.instagram.com/p/{media_id}/",
            http_status=publish_resp.status_code,
            body_preview=(publish_resp.body_text or "")[:300],
        )
    return SocialPublishAttempt(
        status="error",
        real=False,
        platform="instagram",
        error=f"Instagram media_publish failed HTTP {publish_resp.status_code}",
        http_status=publish_resp.status_code,
        body_preview=(publish_resp.body_text or "")[:300],
    )


def publish_youtube(
    *,
    secret: str,
    title: str,
    description: str,
    media_url: str,
    trusted_hosts: tuple[str, ...],
    action_name: str,
    idempotency_key: str | None,
    privacy_status: str = "private",
) -> SocialPublishAttempt:
    """YouTube Data API video insert via resumable upload (media_url required).

    Fail closed without HTTPS media_url. Does not invent post ids.
    """

    if not media_url:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="youtube",
            error="youtube_publish_requires_https_media_url",
            reason="media_url_required",
        )
    if not title:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="youtube",
            error="youtube_publish_requires_title",
            reason="title_required",
        )
    host = trusted_hosts[0] if trusted_hosts else YOUTUBE_TRUSTED_HOSTS[0]
    allowed = list(trusted_hosts or YOUTUBE_TRUSTED_HOSTS)
    privacy = privacy_status if privacy_status in {"private", "unlisted", "public"} else "private"
    query = urlencode({"uploadType": "resumable", "part": "snippet,status"})
    init_url = f"https://{host}/upload/youtube/v3/videos?{query}"
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    snippet_body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    _dest, init_resp = get_default_network_egress_authority().request(
        method="POST",
        url=init_url,
        headers=headers,
        json_body=snippet_body,
        allowed_hosts=allowed,
        action_name=action_name,
        timeout_seconds=30.0,
    )
    # Resumable session URL is typically in Location header; without binary upload
    # completion we fail closed rather than invent a video id.
    location = ""
    if hasattr(init_resp, "headers") and isinstance(init_resp.headers, dict):
        location = str(init_resp.headers.get("Location") or init_resp.headers.get("location") or "")
    parsed = _parse_json_body(init_resp.body_text)
    if _http_is_success(init_resp.status_code) and parsed.get("id"):
        video_id = str(parsed["id"])
        return SocialPublishAttempt(
            status="published",
            real=True,
            platform="youtube",
            provider_post_id=video_id,
            destination_url=f"https://www.youtube.com/watch?v={video_id}",
            http_status=init_resp.status_code,
            body_preview=(init_resp.body_text or "")[:300],
        )
    if _http_is_success(init_resp.status_code) and location:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="youtube",
            error=(
                "youtube_resumable_session_opened_but_binary_upload_not_completed; "
                "provide operator-side media upload completion or use a full video insert path"
            ),
            reason="resumable_upload_incomplete",
            http_status=init_resp.status_code,
            body_preview=location[:300],
        )
    return SocialPublishAttempt(
        status="error",
        real=False,
        platform="youtube",
        error=f"YouTube video insert failed HTTP {init_resp.status_code}",
        http_status=init_resp.status_code,
        body_preview=(init_resp.body_text or "")[:300],
    )


def publish_linkedin(
    *,
    secret: str,
    author_urn: str,
    commentary: str,
    trusted_hosts: tuple[str, ...],
    action_name: str,
    idempotency_key: str | None,
) -> SocialPublishAttempt:
    if not author_urn:
        return SocialPublishAttempt(
            status="error",
            real=False,
            platform="linkedin",
            error="linkedin_publish_requires_author_urn",
            reason="destination_id_required",
        )
    host = trusted_hosts[0] if trusted_hosts else LINKEDIN_PUBLISH_TRUSTED_HOSTS[0]
    url = f"https://{host}/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if idempotency_key:
        headers["X-RestLi-Idempotency-Key"] = idempotency_key
        headers["Idempotency-Key"] = idempotency_key
    body = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": commentary[:3000]},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    _dest, resp = get_default_network_egress_authority().request(
        method="POST",
        url=url,
        headers=headers,
        json_body=body,
        allowed_hosts=list(trusted_hosts or LINKEDIN_PUBLISH_TRUSTED_HOSTS),
        action_name=action_name,
        timeout_seconds=20.0,
    )
    parsed = _parse_json_body(resp.body_text)
    post_id = parsed.get("id")
    if _http_is_success(resp.status_code) and post_id:
        return SocialPublishAttempt(
            status="published",
            real=True,
            platform="linkedin",
            provider_post_id=str(post_id),
            destination_url=None,
            http_status=resp.status_code,
            body_preview=(resp.body_text or "")[:300],
        )
    return SocialPublishAttempt(
        status="error",
        real=False,
        platform="linkedin",
        error=f"LinkedIn ugcPosts publish failed HTTP {resp.status_code}",
        http_status=resp.status_code,
        body_preview=(resp.body_text or "")[:300],
    )


def execute_platform_publish(
    *,
    platform: str,
    secret: str,
    inp: GtmSocialPublishInput,
    trusted_hosts: tuple[str, ...],
    action_name: str,
    idempotency_key: str | None,
) -> SocialPublishAttempt:
    dest = _destination_id(inp)
    media = _media_url(inp)
    title = _title(inp)
    hosts = trusted_hosts or trusted_hosts_for_platform(platform)
    if platform == "facebook":
        if not dest:
            return SocialPublishAttempt(
                status="error",
                real=False,
                platform=platform,
                error="facebook_publish_requires_page_id",
                reason="destination_id_required",
            )
        return publish_facebook_page(
            secret=secret,
            page_id=dest,
            message=inp.content,
            trusted_hosts=hosts,
            action_name=action_name,
            idempotency_key=idempotency_key,
        )
    if platform == "instagram":
        if not dest:
            return SocialPublishAttempt(
                status="error",
                real=False,
                platform=platform,
                error="instagram_publish_requires_ig_user_id",
                reason="destination_id_required",
            )
        return publish_instagram(
            secret=secret,
            ig_user_id=dest,
            caption=inp.content,
            image_url=media,
            trusted_hosts=hosts,
            action_name=action_name,
            idempotency_key=idempotency_key,
        )
    if platform == "youtube":
        return publish_youtube(
            secret=secret,
            title=title or inp.content[:100],
            description=inp.content,
            media_url=media,
            trusted_hosts=hosts,
            action_name=action_name,
            idempotency_key=idempotency_key,
            privacy_status=str((inp.context or {}).get("privacy_status") or "private"),
        )
    if platform == "linkedin":
        return publish_linkedin(
            secret=secret,
            author_urn=dest,
            commentary=inp.content,
            trusted_hosts=hosts,
            action_name=action_name,
            idempotency_key=idempotency_key,
        )
    return SocialPublishAttempt(
        status="error",
        real=False,
        platform=platform,
        error=f"unsupported_social_platform:{platform}",
        reason="unsupported_platform",
    )


def build_social_publish_result(
    *,
    inv: ToolInvocation,
    ctx: ActionRuntimeContext,
    inp: GtmSocialPublishInput,
    social_cred: Any | None,
    make_evidence: Any,
) -> ActionResult:
    """Run fail-closed social publish with durable idempotency and evidence."""

    platform = normalize_platform(inp.platform)
    published: dict[str, Any] = {
        "platform": platform,
        "content": inp.content,
        "status": "error",
        "real": False,
        "provider": "external_social",
        "tenant_id": ctx.tenant_id,
        "action": inv.action,
    }

    if platform not in SUPPORTED_PLATFORMS:
        published["error"] = f"unsupported_social_platform:{platform}"
        published["reason"] = "unsupported_platform"
        return _result(inv, ctx, published, make_evidence)

    secret = getattr(social_cred, "secret_value", None) if social_cred is not None else None
    if isinstance(secret, str):
        secret = secret.strip() or None
    try:
        require_external_secret(secret=secret, action=inv.action)
    except ValueError as exc:
        published["error"] = str(exc)
        published["reason"] = "missing_credential"
        return _result(inv, ctx, published, make_evidence)

    if not secret and allow_simulated_external():
        published["status"] = "simulated"
        published["real"] = False
        published["reason"] = "simulated_external_allowed"
        return _result(inv, ctx, published, make_evidence)

    assert secret is not None

    # High-risk external write: durable claim before provider call.
    claim = claim_smtp_send(
        session_factory=ctx.session_factory,
        tenant_id=ctx.tenant_id,
        action=inv.action,
        idempotency_key=inv.idempotency_key,
    )
    if claim.decision == "replayed":
        cached = dict(claim.cached_output or {})
        cached["idempotency_key"] = claim.idempotency_key
        cached["idempotency_replayed"] = True
        cached.setdefault("platform", platform)
        cached.setdefault("real", True)
        cached.setdefault("status", "published")
        return _result(inv, ctx, cached, make_evidence)
    if claim.decision in {"rejected", "in_flight"}:
        published["error"] = claim.error or "social publish blocked by idempotency gate"
        published["reason"] = "idempotency_gate"
        if claim.idempotency_key:
            published["idempotency_key"] = claim.idempotency_key
        return _result(inv, ctx, published, make_evidence)

    assert claim.idempotency_key is not None
    claim_key = claim.idempotency_key
    published["idempotency_key"] = claim_key

    material_hosts = ()
    if social_cred is not None:
        raw_hosts = getattr(social_cred, "trusted_destination_hosts", None)
        if raw_hosts:
            material_hosts = tuple(str(h) for h in raw_hosts)
    hosts = material_hosts or trusted_hosts_for_platform(platform)

    try:
        attempt = execute_platform_publish(
            platform=platform,
            secret=secret,
            inp=inp,
            trusted_hosts=hosts,
            action_name=inv.action,
            idempotency_key=claim_key,
        )
        published["status"] = attempt.status
        published["real"] = attempt.real
        if attempt.provider_post_id:
            published["provider_post_id"] = attempt.provider_post_id
        if attempt.destination_url:
            published["destination_url"] = attempt.destination_url
        if attempt.error:
            published["error"] = attempt.error
        if attempt.reason:
            published["reason"] = attempt.reason
        if attempt.http_status is not None:
            published["http_status"] = attempt.http_status
        if attempt.body_preview:
            published["body_preview"] = attempt.body_preview
        dest_id = _destination_id(inp)
        if dest_id:
            published["destination_id"] = dest_id

        if attempt.real:
            complete_smtp_send(
                session_factory=ctx.session_factory,
                tenant_id=ctx.tenant_id,
                action=inv.action,
                idempotency_key=claim_key,
                result_payload={
                    "platform": platform,
                    "content": inp.content,
                    "status": "published",
                    "real": True,
                    "provider": "external_social",
                    "provider_post_id": attempt.provider_post_id,
                    "destination_url": attempt.destination_url,
                    "destination_id": dest_id or None,
                    "idempotency_key": claim_key,
                    "tenant_id": ctx.tenant_id,
                    "action": inv.action,
                },
            )
        else:
            release_smtp_send(
                session_factory=ctx.session_factory,
                tenant_id=ctx.tenant_id,
                action=inv.action,
                idempotency_key=claim_key,
                error_detail=attempt.error,
            )
    except Exception as exc:
        release_smtp_send(
            session_factory=ctx.session_factory,
            tenant_id=ctx.tenant_id,
            action=inv.action,
            idempotency_key=claim_key,
            error_detail=str(exc),
        )
        published["status"] = "error"
        published["real"] = False
        published["error"] = str(exc)
        published["reason"] = "transport_error"

    return _result(inv, ctx, published, make_evidence)


def _result(
    inv: ToolInvocation,
    ctx: ActionRuntimeContext,
    published: dict[str, Any],
    make_evidence: Any,
) -> ActionResult:
    real = bool(published.get("real"))
    summary = (
        f"External social publish completed on {published.get('platform')}"
        if real
        else (
            "External social publish not executed "
            f"({published.get('error') or published.get('reason') or 'blocked'})"
        )
    )
    evidence_payload = {
        "platform": published.get("platform"),
        "status": published.get("status"),
        "real": real,
        "provider_post_id": published.get("provider_post_id"),
        "destination_url": published.get("destination_url"),
        "destination_id": published.get("destination_id"),
        "idempotency_key": published.get("idempotency_key"),
        "tenant_id": ctx.tenant_id,
        "action": inv.action,
        "error": published.get("error"),
    }
    if callable(make_evidence):
        evidence_item = make_evidence(
            inv.action,
            "external_social",
            ctx,
            summary,
            evidence_payload,
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
        )
    else:
        evidence_item = EvidenceItem(
            evidence_type="action_result_evidence",
            evidence_source="social_publish",
            action_name=inv.action,
            tool_provider="external_social",
            tenant_id=ctx.tenant_id,
            task_id=str(ctx.task_id),
            mission_id=str(ctx.mission_id) if ctx.mission_id else None,
            summary=summary,
            structured_payload=evidence_payload,
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
        )
    return ActionResult(
        action=inv.action,
        provider="external_social",
        side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
        output=published,
        evidence=[evidence_item],
        summary=summary,
    )
