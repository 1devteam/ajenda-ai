"""GTM actions for lead enrichment and email drafting (PR6 expansion).

Core actions implemented with evidence, side-effect classification, and credential requirements for high-risk external.
Local/simulated providers for proof-of-concept and CI; production uses credential injection + egress authority.
"""

from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.document_artifacts import read_artifact, update_review_status
from backend.services.draft_generation import generate_and_persist_draft
from backend.services.network_egress import get_default_network_egress_authority
from backend.services.plugins.crm_client import default_crm_client, is_live_external_crm_result
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
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
from backend.services.tools.external_sim_policy import allow_simulated_external
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    GtmCrmUpsertInput,
    GtmEmailCheckInput,
    GtmEmailDraftInput,
    GtmEmailSendInput,
    GtmLeadEnrichInput,
    GtmSocialPublishInput,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.tools.side_effect_resolvers import credential_reference_external_write


def _get_runtime_credential(
    ctx: ActionRuntimeContext,
    *,
    action: str,
    aliases: tuple[str, ...] = (),
) -> RuntimeCredentialMaterial | dict[str, Any] | None:
    credentials = ctx.runtime_credentials
    for key in (action, *aliases):
        if key in credentials:
            return credentials[key]
    return None


def _credential_secret(material: RuntimeCredentialMaterial | dict[str, Any] | None) -> str | None:
    if material is None:
        return None
    if isinstance(material, dict):
        secret = material.get("secret_value")
        return str(secret) if isinstance(secret, str) and secret else None
    return material.secret_value


def _gmail_user(material: RuntimeCredentialMaterial | dict[str, Any] | None, *, default: str = "me") -> str:
    if material is None:
        return default
    if isinstance(material, dict):
        for field in ("user", "email"):
            value = material.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        reference = material.get("reference")
        if isinstance(reference, str) and "@" in reference:
            return reference.strip()
        return default
    for header_name in ("X-Gmail-User", "gmail-user"):
        injected = material.injected_headers.get(header_name)
        if isinstance(injected, str) and injected.strip():
            return injected.strip()
    credential_id = material.reference.credential_id
    if "@" in credential_id:
        return credential_id
    return default


def _trusted_hosts(
    material: RuntimeCredentialMaterial | dict[str, Any] | None,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if material is None:
        return default
    if isinstance(material, dict):
        raw_hosts = material.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return default
    if material.trusted_destination_hosts:
        return material.trusted_destination_hosts
    return default


def _gmail_api_send_payload(*, to: str, subject: str, body: str) -> dict[str, str]:
    message = MIMEText(body or " ")
    message["To"] = to
    message["Subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return {"raw": raw}


def _http_is_success(status_code: int) -> bool:
    return 200 <= status_code < 300


def _ensure_simulated_external_outcome(payload: dict[str, Any], *, reason: str) -> None:
    """Fail-closed: non-real external actions must not use success-looking status values."""
    if payload.get("real"):
        return
    if payload.get("status") == "error":
        return
    payload["status"] = "simulated"
    payload["real"] = False
    payload.setdefault("reason", reason)


def _provider_headers(base: dict[str, str], inv: ToolInvocation) -> dict[str, str]:
    headers = dict(base)
    if inv.idempotency_key and inv.idempotency_key.strip():
        headers["Idempotency-Key"] = inv.idempotency_key.strip()
    return headers


def _provider_body(body: dict[str, Any], inv: ToolInvocation) -> dict[str, Any]:
    if inv.idempotency_key and inv.idempotency_key.strip():
        return {**body, "idempotency_key": inv.idempotency_key.strip()}
    return body


def _sent_message_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a privacy-bounded canonical artifact for the send attempt."""

    row: dict[str, Any] = {
        "to": payload.get("to"),
        "subject": payload.get("subject"),
        "artifact_id": payload.get("artifact_id"),
        "status": payload.get("status"),
        "real": payload.get("real") is True,
        "provider": payload.get("provider"),
    }
    for key in ("idempotency_key", "provider_message_id", "idempotency_replayed", "error", "reason"):
        if payload.get(key) is not None:
            row[key] = payload[key]
    return [row]


def _make_evidence(
    action: str,
    provider: str,
    context: ActionRuntimeContext,
    summary: str,
    payload: dict[str, Any],
    *,
    side_effect_class: SideEffectClass = SideEffectClass.NONE,
    provenance: dict[str, Any] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="gtm_actions",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=payload,
        side_effect_class=side_effect_class,
        provenance=provenance or {},
    )


def register_gtm_actions(registry: ActionRegistry) -> None:
    def lead_enrich_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        merged_input = dict(inv.input)
        prospects_in = [p for p in (merged_input.get("prospects") or []) if isinstance(p, dict)]
        company_seed = str(merged_input.get("company", "") or "").strip()
        domain_seed = str(merged_input.get("domain", "") or "").strip() or None

        # Prefer bound prospects; do not overwrite prospect company with tenant profile.
        if not company_seed and prospects_in:
            company_seed = str(prospects_in[0].get("company") or "").strip()
            domain_seed = domain_seed or (str(prospects_in[0].get("domain") or "").strip() or None)
        if company_seed:
            merged_input["company"] = company_seed
        if domain_seed:
            merged_input["domain"] = domain_seed
        inp = GtmLeadEnrichInput.model_validate(merged_input)

        if bool(inp.context.get("binding_required")) and not prospects_in:
            raise ValueError(
                "gtm.lead_enrich requires bound upstream prospects when composition marks binding_required"
            )

        source_prospects = prospects_in or [
            {
                "prospect_id": f"enrich:{inp.company}",
                "company": inp.company,
                "domain": inp.domain or domain_seed,
            }
        ]
        enriched_prospects: list[dict[str, Any]] = []
        for index, prospect in enumerate(source_prospects):
            company = str(prospect.get("company") or inp.company or f"prospect-{index + 1}")[:160]
            domain = str(prospect.get("domain") or inp.domain or domain_seed or "").strip() or None
            existing = [item for item in (prospect.get("contacts") or []) if isinstance(item, dict)]
            real_existing = [
                item for item in existing if item.get("real") is True and item.get("simulated") is not True
            ]
            contacts: list[dict[str, Any]] = list(real_existing)
            enrichment_mode = "passthrough_observed"
            enrichment_real = bool(real_existing)
            if not contacts and domain and allow_simulated_external():
                contacts.append(
                    {
                        "email": f"contact@{domain}",
                        "role": str(prospect.get("role") or "Owner"),
                        "real": False,
                        "simulated": True,
                        "source": "local_gtm_heuristic",
                    }
                )
                enrichment_mode = "local_simulated"
                enrichment_real = False
            elif not contacts:
                enrichment_mode = "unresolved"
                enrichment_real = False
            enriched_prospects.append(
                {
                    **{k: v for k, v in prospect.items() if k not in {"contacts"}},
                    "prospect_id": str(prospect.get("prospect_id") or f"enrich:{index}:{company}")[:80],
                    "company": company,
                    "domain": domain,
                    "contacts": contacts,
                    "enrichment_real": enrichment_real,
                    "enrichment_mode": enrichment_mode,
                    "context": inp.context,
                }
            )

        primary = enriched_prospects[0]
        enriched = {
            "company": primary["company"],
            "domain": primary.get("domain"),
            "contacts": primary.get("contacts") or [],
            "context": inp.context,
            "enriched_prospects": enriched_prospects,
            "prospect_count": len(enriched_prospects),
            "real": any(item.get("enrichment_real") for item in enriched_prospects),
            "simulated": any(item.get("enrichment_mode") == "local_simulated" for item in enriched_prospects),
        }
        mode = str(primary.get("enrichment_mode") or "unresolved")
        summary = (
            f"Enriched {len(enriched_prospects)} prospect(s) ({mode})"
            if mode != "unresolved"
            else f"No real contacts available for {len(enriched_prospects)} prospect(s); none invented"
        )
        return ActionResult(
            action=inv.action,
            provider="local_gtm",
            side_effect_class=SideEffectClass.NONE,
            output=enriched,
            evidence=[_make_evidence(inv.action, "local_gtm", ctx, summary, enriched)],
            summary=summary,
        )

    def email_draft_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = GtmEmailDraftInput.model_validate(inv.input)
        prospects = [p for p in inp.prospects if isinstance(p, dict)]
        draft_rows: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        work_items = prospects or [{}]
        for primary in work_items:
            context = dict(inp.context)
            recipient = inp.recipient
            topic = inp.topic
            company = str(primary.get("company") or context.get("prospect_company") or "").strip()
            if company:
                context["prospect_company"] = company
            if primary.get("domain"):
                context["prospect_domain"] = primary.get("domain")
            if primary.get("signals"):
                context["upstream_signals"] = primary.get("signals")
            if primary.get("reasons"):
                context["qualification_reasons"] = primary.get("reasons")
            if primary.get("score") is not None:
                context["qualification_score"] = primary.get("score")
            raw_contacts = primary.get("contacts")
            contacts: list[Any] = raw_contacts if isinstance(raw_contacts, list) else []
            for contact in contacts:
                if not isinstance(contact, dict) or not contact.get("email"):
                    continue
                bound_email = str(contact["email"]).strip()
                simulated = bool(contact.get("simulated") or contact.get("real") is False)
                context["contact_email_simulated"] = simulated
                if not simulated and (not recipient or str(recipient).endswith("@invalid.local")):
                    recipient = bound_email
                    context["recipient_bound"] = True
                break
            if company and (not topic or topic.startswith("Introduction")):
                topic = f"Introduction — {company}"[:240]

            draft = generate_and_persist_draft(
                ctx,
                artifact_type="pitch_email",
                topic=topic,
                tone=inp.tone,
                recipient=recipient,
                extra_context=context,
            )
            drafts.append(draft)
            draft_rows.append(
                {
                    "prospect_id": primary.get("prospect_id"),
                    "company": context.get("prospect_company"),
                    "recipient": draft.get("to"),
                    "subject": draft.get("subject"),
                    "artifact_id": draft.get("artifact_id"),
                    "recipient_bound": bool(context.get("recipient_bound")),
                }
            )

        draft = dict(drafts[0])
        draft["prospects"] = prospects
        draft["introduction_drafts"] = draft_rows
        draft["draft_count"] = len(draft_rows)
        mode = draft.get("generation_mode", "template")
        summary = f"Drafted email ({mode})"
        if context.get("prospect_company"):
            summary = f"Drafted email for {context['prospect_company']} ({mode})"
        return ActionResult(
            action=inv.action,
            provider="local_gtm",
            side_effect_class=SideEffectClass.NONE,
            output=draft,
            evidence=[_make_evidence(inv.action, "local_gtm", ctx, summary, draft)],
            summary=summary,
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

    def crm_upsert_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = GtmCrmUpsertInput.model_validate(inv.input)

        crm_cred = None
        for key in (inv.action, "gtm.crm_upsert", "external_crm"):
            if key in getattr(ctx, "runtime_credentials", {}):
                crm_cred = ctx.runtime_credentials[key]
                break

        result = default_crm_client().upsert(
            context=ctx,
            record_type=inp.record_type,
            data=inp.data,
            credential=crm_cred,
            invocation=inv,
            action_name=inv.action,
        )
        use_external = is_live_external_crm_result(
            source=result.source,
            real=result.real,
            error=result.error,
        )
        upserted: dict[str, Any] = {
            "record_type": result.record_type,
            "id": result.record_id or f"crm_{str(ctx.task_id)[:8]}",
            "data": result.data,
            "status": result.status,
            "real": result.real,
            "source": result.source,
            "plugin_required": use_external,
        }
        if result.error:
            upserted["error"] = result.error
        if result.status_code is not None:
            upserted["real_response"] = {"status_code": result.status_code}
        if inv.idempotency_key and result.real:
            upserted["idempotency_key"] = inv.idempotency_key

        provider = "ajenda_brain"
        side_effect = (
            SideEffectClass.EXTERNAL_WRITE if inv.credential_reference is not None else SideEffectClass.INTERNAL_WRITE
        )
        summary = (
            "External CRM upsert completed via plugin"
            if use_external
            else "Internal CRM upsert completed in Ajenda brain"
        )

        return ActionResult(
            action=inv.action,
            provider=provider,
            side_effect_class=side_effect,
            output=upserted,
            evidence=[
                _make_evidence(
                    inv.action,
                    provider,
                    ctx,
                    summary,
                    upserted,
                    side_effect_class=side_effect,
                )
            ],
            records_changed=[str(upserted["id"])] if result.real else [],
            summary=summary,
        )

    registry.register(
        ActionDefinition(
            name="gtm.lead_enrich",
            handler=lead_enrich_handler,
            side_effect_class=SideEffectClass.NONE,
            provider="local_gtm",
            input_model=GtmLeadEnrichInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_draft",
            handler=email_draft_handler,
            side_effect_class=SideEffectClass.NONE,
            provider="local_gtm",
            input_model=GtmEmailDraftInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_send",
            handler=email_send_handler,
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            provider="external_email",
            input_model=GtmEmailSendInput,
            credential_requirement=CredentialRequirement(
                provider="external_email",
                credential_type="api_key",
                # Gmail API bearer (api_key) or SMTP JSON (smtp / platform_master email master).
                allowed_credential_types=("api_key", "smtp", "platform_master"),
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,),
            ),
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_check",
            handler=email_check_handler,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            provider="external_email",
            input_model=GtmEmailCheckInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.crm_upsert",
            handler=crm_upsert_handler,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            side_effect_resolver=credential_reference_external_write,
            provider="ajenda_brain",
            input_model=GtmCrmUpsertInput,
        )
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
                    trusted = getattr(social_cred, "trusted_destination_hosts", None) or ("api.social.example.com",)
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

    registry.register(
        ActionDefinition(
            name="gtm.social_publish",
            handler=social_publish_handler,
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
            provider="external_social",
            input_model=GtmSocialPublishInput,
            credential_requirement=CredentialRequirement(
                provider="external_social",
                credential_type="api_key",
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_PUBLISH,),
            ),
        )
    )
