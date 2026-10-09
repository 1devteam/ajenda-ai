"""GTM social publish handler."""

from typing import Any

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.gtm_action_common import (
    _ensure_simulated_external_outcome,
    _http_is_success,
    _make_evidence,
    _provider_body,
    _provider_headers,
)
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    GtmSocialPublishInput,
    SideEffectClass,
    ToolInvocation,
)


def social_publish_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    inp = GtmSocialPublishInput.model_validate(inv.input)

    # Push real path for social: use network_egress + cred like CRM/email
    social_cred = None
    for k in (inv.action, "gtm.social_publish", "external_social"):
        if k in getattr(ctx, "runtime_credentials", {}):
            social_cred = ctx.runtime_credentials[k]
            break

    published: dict[str, Any] = {
        "platform": inp.platform,
        "content": inp.content,
        "status": "simulated",
        "real": False,
        "reason": "no_runtime_credential",
    }

    if social_cred:
        try:
            secret = getattr(social_cred, "secret_value", None)
            if secret:
                trusted = tuple(getattr(social_cred, "trusted_destination_hosts", None) or ())
                if not trusted:
                    raise ValueError("social publish credential has no trusted destination host")
                publish_url = f"https://{trusted[0]}/publish"
                headers = _provider_headers(
                    {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                    inv,
                )
                body = _provider_body({"platform": inp.platform, "content": inp.content}, inv)
                _dest, resp = get_default_network_egress_authority().request(
                    method="POST",
                    url=publish_url,
                    headers=headers,
                    json_body=body,
                    allowed_hosts=list(trusted),
                    action_name=inv.action,
                    timeout_seconds=10.0,
                )
                published["real_response"] = {
                    "status_code": resp.status_code,
                    "body_preview": resp.body_text[:300] if resp.body_text else "",
                }
                if _http_is_success(resp.status_code):
                    published["status"] = "published_real"
                    published["credential_used"] = True
                    published["real"] = True
                    if inv.idempotency_key:
                        published["idempotency_key"] = inv.idempotency_key
                else:
                    published["status"] = "error"
                    published["real"] = False
                    published["error"] = f"Social API returned HTTP {resp.status_code}"
        except Exception as e:
            published["status"] = "error"
            published["error"] = str(e)
            published["real"] = False

    if published.get("real"):
        published.setdefault("post_id", "post_" + str(ctx.task_id)[:8])
        published.setdefault("url", f"https://{inp.platform}.com/post/{str(ctx.task_id)[:8]}")

    _ensure_simulated_external_outcome(
        published,
        reason="runtime_credential_missing_or_publish_not_executed",
    )

    return ActionResult(
        action=inv.action,
        provider="external_social",
        side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
        output=published,
        evidence=[
            _make_evidence(
                inv.action,
                "external_social",
                ctx,
                "External social publish completed"
                if published.get("real")
                else "External social publish not executed (simulated; no publish effect)",
                published,
                side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
            )
        ],
        summary="External social publish completed (real via cred)"
        if published.get("real")
        else "External social publish not executed (simulated; no publish effect)",
    )
