"""GTM email send/check handlers."""

from __future__ import annotations

import json

from typing import Any

from urllib.parse import quote

from backend.services.document_artifacts import read_artifact, update_review_status

from backend.services.network_egress import get_default_network_egress_authority

from backend.services.tools.email_send_idempotency import (
    claim_smtp_send,
    complete_smtp_send,
    release_smtp_send,
)

from backend.services.tools.email_transport import (
    credential_transport_mode,
    parse_smtp_secret,
    send_via_smtp,
)

from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    GtmEmailCheckInput,
    GtmEmailSendInput,
    SideEffectClass,
    ToolInvocation,
)

from backend.services.tools.gtm_action_common import (
    _credential_secret,
    _ensure_simulated_external_outcome,
    _get_runtime_credential,
    _gmail_api_send_payload,
    _gmail_user,
    _http_is_success,
    _make_evidence,
    _provider_body,
    _provider_headers,
    _sent_message_rows,
    _trusted_hosts,
)

def _resolve_send_content(
    inv: ToolInvocation,
    ctx: ActionRuntimeContext,
    inp: GtmEmailSendInput,
) -> tuple[str, str, str, str | None]:
    artifact_id = inp.artifact_id or str(inp.context.get("artifact_id", "") or "").strip() or None
    to = inp.to
    subject = inp.subject or str(inp.context.get("subject", "") or "")
    body_text = inp.body or str(inp.context.get("body", "") or "")

    if artifact_id and ctx.session_factory is not None:
        session = ctx.session_factory()
        try:
            artifact = read_artifact(session, tenant_id=ctx.tenant_id, artifact_id=artifact_id)
        finally:
            session.close()
        if artifact is not None:
            content = artifact.get("content")
            if isinstance(content, dict):
                body_text = str(content.get("body") or content.get("draft") or body_text)
                subject = str(content.get("subject") or subject)
                to = str(content.get("to") or to)
            review_status = str(artifact.get("review_status") or "")
            if review_status not in {"approved", "sent"}:
                raise ValueError(f"artifact {artifact_id} is not approved for send (status={review_status})")
    if not subject.strip():
        raise ValueError("subject is required for gtm.email_send")
    if not body_text.strip():
        raise ValueError("body is required for gtm.email_send")
    return to, subject.strip(), body_text.strip(), artifact_id


def email_send_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    inp = GtmEmailSendInput.model_validate(inv.input)
    requested_artifact_id = inp.artifact_id or str(inp.context.get("artifact_id", "") or "").strip() or None
    try:
        to, subject, body_text, artifact_id = _resolve_send_content(inv, ctx, inp)
    except ValueError as exc:
        blocked_output = {
            "to": inp.to,
            "subject": inp.subject,
            "body": inp.body,
            "status": "error",
            "real": False,
            "error": str(exc),
            "context": inp.context,
            "artifact_id": requested_artifact_id,
        }
        blocked_output["sent_messages"] = _sent_message_rows(blocked_output)
        return ActionResult(
            action=inv.action,
            provider="external_email",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            output=blocked_output,
            evidence=[
                _make_evidence(
                    inv.action,
                    "external_email",
                    ctx,
                    "External email blocked by artifact review gate",
                    blocked_output,
                    side_effect_class=SideEffectClass.EXTERNAL_SEND,
                )
            ],
            summary="External email blocked by artifact review gate",
        )

    gmail_cred = _get_runtime_credential(
        ctx,
        action=inv.action,
        aliases=("gtm.email_send", "external_email"),
    )

    sent: dict[str, Any] = {
        "to": to,
        "subject": subject,
        "body": body_text,
        "status": "simulated",
        "context": inp.context,
        "artifact_id": artifact_id,
        "real": False,
        "reason": "no_runtime_credential",
    }

    secret = _credential_secret(gmail_cred)
    if secret:
        transport = credential_transport_mode(gmail_cred)
        try:
            if transport == "smtp":
                # SMTP has no provider-side Idempotency-Key. Claim durably
                # before sendmail so worker retries cannot double-deliver.
                claim = claim_smtp_send(
                    session_factory=ctx.session_factory,
                    tenant_id=ctx.tenant_id,
                    action=inv.action,
                    idempotency_key=inv.idempotency_key,
                )
                if claim.decision == "replayed":
                    cached = dict(claim.cached_output or {})
                    sent.update(cached)
                    sent["idempotency_key"] = claim.idempotency_key
                    sent["idempotency_replayed"] = True
                    sent.setdefault("provider", "smtp")
                    sent.setdefault("status", "sent")
                    sent.setdefault("real", True)
                elif claim.decision in {"rejected", "in_flight"}:
                    sent["provider"] = "smtp"
                    sent["status"] = "error"
                    sent["real"] = False
                    sent["error"] = claim.error or "smtp send blocked by idempotency gate"
                    if claim.idempotency_key:
                        sent["idempotency_key"] = claim.idempotency_key
                else:
                    assert claim.idempotency_key is not None
                    claim_key = claim.idempotency_key
                    try:
                        smtp_config = parse_smtp_secret(secret)
                        smtp_result = send_via_smtp(
                            config=smtp_config,
                            to=to,
                            subject=subject,
                            body=body_text,
                            message_id=claim_key,
                        )
                        sent["provider"] = smtp_result.provider
                        sent["status"] = smtp_result.status
                        sent["real"] = smtp_result.real
                        if smtp_result.error:
                            sent["error"] = smtp_result.error
                        if smtp_result.real:
                            sent["idempotency_key"] = claim_key
                            complete_smtp_send(
                                session_factory=ctx.session_factory,
                                tenant_id=ctx.tenant_id,
                                action=inv.action,
                                idempotency_key=claim_key,
                                result_payload={
                                    "to": to,
                                    "subject": subject,
                                    "body": body_text,
                                    "status": smtp_result.status,
                                    "real": True,
                                    "provider": smtp_result.provider,
                                    "idempotency_key": claim_key,
                                    "context": inp.context,
                                    "artifact_id": artifact_id,
                                },
                            )
                        else:
                            release_smtp_send(
                                session_factory=ctx.session_factory,
                                tenant_id=ctx.tenant_id,
                                action=inv.action,
                                idempotency_key=claim_key,
                                error_detail=smtp_result.error,
                            )
                    except Exception as send_exc:
                        # Pre-send / transport failure after claim: release so retry can re-claim.
                        # Post-send crash before complete stays "claiming" (fail closed, no double send).
                        release_smtp_send(
                            session_factory=ctx.session_factory,
                            tenant_id=ctx.tenant_id,
                            action=inv.action,
                            idempotency_key=claim_key,
                            error_detail=str(send_exc),
                        )
                        raise
            else:
                user = _gmail_user(gmail_cred)
                trusted_hosts = _trusted_hosts(gmail_cred, default=("gmail.googleapis.com",))
                send_url = f"https://{trusted_hosts[0]}/gmail/v1/users/{quote(user, safe='')}/messages/send"
                headers = _provider_headers(
                    {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                    inv,
                )
                _dest, resp = get_default_network_egress_authority().request(
                    method="POST",
                    url=send_url,
                    headers=headers,
                    json_body=_gmail_api_send_payload(to=to, subject=subject, body=body_text),
                    allowed_hosts=list(trusted_hosts),
                    action_name=inv.action,
                    timeout_seconds=10.0,
                )
                sent["real_response"] = {
                    "status_code": resp.status_code,
                    "body_preview": resp.body_text[:300] if resp.body_text else "",
                }
                if _http_is_success(resp.status_code):
                    sent["status"] = "sent"
                    sent["real"] = True
                    sent["provider"] = "gmail_api"
                    try:
                        response_payload = json.loads(resp.body_text or "{}")
                    except json.JSONDecodeError:
                        response_payload = {}
                    provider_message_id = response_payload.get("id")
                    if isinstance(provider_message_id, str) and provider_message_id.strip():
                        sent["provider_message_id"] = provider_message_id.strip()
                else:
                    sent["status"] = "error"
                    sent["real"] = False
                    sent["error"] = f"Gmail API returned HTTP {resp.status_code}"
            if sent.get("real") and inv.idempotency_key:
                sent["idempotency_key"] = inv.idempotency_key
        except Exception as e:
            sent["status"] = "error"
            sent["error"] = str(e)
            sent["real"] = False

    _ensure_simulated_external_outcome(
        sent,
        reason="runtime_credential_missing_or_send_not_executed",
    )
    sent["sent_messages"] = _sent_message_rows(sent)

    if ctx.session_factory is not None and (
        (sent.get("real") and artifact_id) or sent.get("status") in {"sent", "simulated"}
    ):
        from backend.services.light_crm.workflow import on_email_sent

        session = ctx.session_factory()
        try:
            if sent.get("real") and artifact_id:
                update_review_status(
                    session,
                    tenant_id=ctx.tenant_id,
                    artifact_id=artifact_id,
                    review_status="sent",
                    actor="system:gtm.email_send",
                )
            if sent.get("status") in {"sent", "simulated"}:
                on_email_sent(
                    session=session,
                    tenant_id=ctx.tenant_id,
                    to=to,
                    subject=subject,
                    artifact_id=artifact_id,
                    sent_real=bool(sent.get("real")),
                    mission_id=str(ctx.mission_id) if ctx.mission_id else None,
                    task_id=str(ctx.task_id) if ctx.task_id else None,
                )
            session.commit()
        finally:
            session.close()

    if sent.get("real"):
        transport_label = {
            "gmail_api": "Gmail API",
            "smtp": "SMTP",
        }.get(str(sent.get("provider") or ""), "external email")
        send_summary = f"External email sent via {transport_label}"
    else:
        send_summary = "External email not sent (simulated; no outbound effect)"

    return ActionResult(
        action=inv.action,
        provider="external_email",
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
        output=sent,
        evidence=[
            _make_evidence(
                inv.action,
                "external_email",
                ctx,
                send_summary,
                sent,
                side_effect_class=SideEffectClass.EXTERNAL_SEND,
            )
        ],
        summary=send_summary,
    )

def email_check_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    """Check/read recent emails from Gmail (supports real via credential or simulated)."""
    inp = GtmEmailCheckInput.model_validate(inv.input)
    gmail_cred = _get_runtime_credential(
        ctx,
        action=inv.action,
        aliases=("gtm.email_check", "external_email", "gmail"),
    )

    emails: list[dict[str, Any]] = []
    secret = _credential_secret(gmail_cred)
    from backend.services.tools.external_sim_policy import require_external_secret

    require_external_secret(secret=secret if isinstance(secret, str) else None, action=inv.action)
    credentialed_path = bool(secret)
    if credentialed_path:
        try:
            user = _gmail_user(gmail_cred)
            trusted_hosts = _trusted_hosts(gmail_cred, default=("gmail.googleapis.com",))
            list_url = (
                f"https://{trusted_hosts[0]}/gmail/v1/users/{quote(user, safe='')}/messages"
                f"?q={quote(inp.query, safe='')}&maxResults={inp.limit}"
            )
            headers = _provider_headers({"Authorization": f"Bearer {secret}"}, inv)
            _dest, resp = get_default_network_egress_authority().request(
                method="GET",
                url=list_url,
                headers=headers,
                json_body=None,
                allowed_hosts=list(trusted_hosts),
                action_name=inv.action,
                timeout_seconds=10.0,
            )
            if not _http_is_success(resp.status_code):
                raise ValueError(f"Gmail API returned HTTP {resp.status_code}")
            payload_json = json.loads(resp.body_text or "{}")
            for message in payload_json.get("messages", [])[: inp.limit]:
                if not isinstance(message, dict):
                    continue
                emails.append(
                    {
                        "id": message.get("id"),
                        "thread_id": message.get("threadId"),
                        "snippet": message.get("snippet"),
                    }
                )
        except Exception as exc:
            raise ValueError(f"Gmail email check failed on credentialed path: {exc}") from exc
    elif not emails:
        emails = [
            {
                "id": "sim-1",
                "from": "example@lead.com",
                "subject": "Follow up",
                "date": "now",
                "snippet": "Simulated email content...",
            },
        ]

    payload = {
        "query": inp.query,
        "limit": inp.limit,
        "emails": emails,
        "real": credentialed_path,
    }
    summary = f"Gmail check ({len(emails)} results)" if credentialed_path else "Gmail check (simulated)"
    return ActionResult(
        action=inv.action,
        provider="external_email",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=payload,
        evidence=[
            _make_evidence(
                inv.action,
                "external_email",
                ctx,
                summary,
                payload,
                side_effect_class=SideEffectClass.EXTERNAL_READ,
            )
        ],
        summary=summary,
    )
