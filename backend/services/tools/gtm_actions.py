"""GTM actions for lead enrichment and email drafting (PR6 expansion).

Core actions implemented with evidence, side-effect classification, and credential requirements for high-risk external.
Local/simulated providers for proof-of-concept and CI; production uses credential injection + egress authority.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.repositories.retrieval_contract_repository import RetrievalContractRepository
from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    GtmCrmUpsertInput,
    GtmEmailDraftInput,
    GtmEmailSendInput,
    GtmLeadEnrichInput,
    GtmSocialPublishInput,
    RetrievalHybridInput,
    SideEffectClass,
    ToolInvocation,
)


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
        inp = GtmLeadEnrichInput.model_validate(inv.input)
        enriched = {
            "company": inp.company,
            "domain": inp.domain or "example.com",
            "contacts": [{"email": "found@example.com", "role": "Owner"}],
            "context": inp.context,
        }
        return ActionResult(
            action=inv.action,
            provider="local_gtm",
            side_effect_class=SideEffectClass.NONE,
            output=enriched,
            evidence=[_make_evidence(inv.action, "local_gtm", ctx, "lead enriched", enriched)],
            summary="Enriched lead data (local proof)",
        )

    def email_draft_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = GtmEmailDraftInput.model_validate(inv.input)
        draft = {
            "to": inp.recipient,
            "subject": f"Re: {inp.topic}",
            "body": f"Hi,\n\nFollowing up on {inp.topic} in {inp.tone} tone.\nContext: {inp.context}\n\nBest, Acme",
        }
        return ActionResult(
            action=inv.action,
            provider="local_gtm",
            side_effect_class=SideEffectClass.NONE,
            output=draft,
            evidence=[_make_evidence(inv.action, "local_gtm", ctx, "email draft", draft)],
            summary="Drafted email (local proof)",
        )

    def retrieval_hybrid_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = RetrievalHybridInput.model_validate(inv.input)
        memories = [
            {"id": "mem1", "content": f"Related to {inp.query}", "score": 0.92},
            {"id": "mem2", "content": "Supporting fact from prior mission", "score": 0.81},
        ]
        contract_summaries: list[dict[str, Any]] = []
        # PR10: full retrieval - use tenant-scoped RetrievalContracts for governance and source evidence
        if inp.mission_id and ctx.session_factory:
            try:
                session = ctx.session_factory()
                repo = RetrievalContractRepository(session)
                contracts = repo.list_for_mission(mission_id=uuid.UUID(inp.mission_id), tenant_id=ctx.tenant_id)
                for c in contracts:
                    summary = {
                        "id": str(c.id),
                        "strategy": c.retrieval_strategy,
                        "reason": c.retrieval_reason,
                        "governance_constraints": c.governance_constraints,
                        "trust_signal": c.trust_signal,
                        "provenance_metadata": c.provenance_metadata,
                        "status": c.retrieval_status,
                    }
                    contract_summaries.append(summary)
                    # Incorporate memory references from the contract as governed source material (demo)
                    for ref in (
                        getattr(c, "returned_memory_references", None) or getattr(c, "memory_references", None) or []
                    ):
                        if isinstance(ref, dict) and ref.get("memory_id"):
                            memories.append(
                                {
                                    "id": str(ref.get("memory_id")),
                                    "source": "retrieval_contract",
                                    "contract_id": str(c.id),
                                }
                            )
            except Exception:
                pass
            finally:
                if "session" in locals():
                    session.close()

        payload: dict[str, Any] = {
            "query": inp.query,
            "memories": memories,
            "filters": inp.filters,
            "retrieval_contracts": contract_summaries,
        }
        inspected: list[str] = []
        for m in memories:
            if isinstance(m, dict):
                mid = m.get("id")
                if isinstance(mid, str):
                    inspected.append(mid)

        provenance: dict[str, Any] = {}
        if contract_summaries:
            provenance = {
                "retrieval_contract_ids": [s["id"] for s in contract_summaries],
                "governance_contract_count": len(contract_summaries),
                "source": "retrieval_contracts",
            }

        evidence = _make_evidence(
            inv.action,
            "local_retrieval",
            ctx,
            "hybrid retrieval (governed)",
            payload,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            provenance=provenance,
        )

        return ActionResult(
            action=inv.action,
            provider="local_retrieval",
            side_effect_class=SideEffectClass.INTERNAL_READ,
            output=payload,
            evidence=[evidence],
            records_inspected=inspected,
            summary=(
                f"Hybrid retrieval (semantic+keyword mock, governed by {len(contract_summaries)} retrieval contract(s))"
                if contract_summaries
                else "Hybrid retrieval (semantic+keyword mock, contract-backed)"
            ),
        )

    def email_send_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = GtmEmailSendInput.model_validate(inv.input)

        # Try real Gmail via credential injected by CredentialRuntimeAuthority
        gmail_cred = None
        for k in (inv.action, "gtm.email_send", "external_email"):
            if k in getattr(ctx, "runtime_credentials", {}):
                gmail_cred = ctx.runtime_credentials[k]
                break

        sent = {
            "to": inp.to,
            "subject": inp.subject,
            "body": getattr(inp, "body", "") or inp.context.get("body", ""),
            "status": "sent",
            "message_id": "msg_" + str(ctx.task_id)[:8],
            "context": inp.context,
            "real": False,
        }

        if gmail_cred:
            try:
                secret = gmail_cred.get("secret_value") if isinstance(gmail_cred, dict) else None
                user = None
                if isinstance(gmail_cred, dict):
                    user = gmail_cred.get("user") or gmail_cred.get("email") or gmail_cred.get("reference")
                if secret and user:
                    import smtplib
                    from email.mime.multipart import MIMEMultipart
                    from email.mime.text import MIMEText

                    msg = MIMEMultipart()
                    msg["From"] = user
                    msg["To"] = inp.to
                    msg["Subject"] = inp.subject
                    msg.attach(MIMEText(sent["body"] or " ", "plain"))

                    server = smtplib.SMTP("smtp.gmail.com", 587)
                    server.starttls()
                    server.login(user, secret)
                    server.send_message(msg)
                    server.quit()

                    sent["status"] = "sent"
                    sent["real"] = True
                    sent["provider"] = "gmail"
            except Exception as e:
                sent["status"] = "error"
                sent["error"] = str(e)
                sent["real"] = False

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
                    "email sent externally" + (" (real Gmail)" if sent.get("real") else " (simulated)"),
                    sent,
                    side_effect_class=SideEffectClass.EXTERNAL_SEND,
                )
            ],
            summary="External email send via Gmail"
            if sent.get("real")
            else "External email send (simulated, requires egress/cred in prod)",
        )

    def email_check_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        """Check/read recent emails from Gmail (supports real via credential or simulated)."""
        # Support for input like {"query": "is:unread", "limit": 5} or simple
        inp = inv.input or {}
        limit = int(inp.get("limit", 5))
        query = inp.get("query", "ALL")  # Gmail search syntax e.g. "from:someone" or "is:unread"

        gmail_cred = None
        for k in (inv.action, "gtm.email_check", "gmail"):
            if k in getattr(ctx, "runtime_credentials", {}):
                gmail_cred = ctx.runtime_credentials[k]
                break

        emails = []
        if gmail_cred:
            try:
                secret = gmail_cred.get("secret_value") if isinstance(gmail_cred, dict) else None
                user = None
                if isinstance(gmail_cred, dict):
                    user = gmail_cred.get("user") or gmail_cred.get("email") or gmail_cred.get("reference")
                if secret and user:
                    import email
                    import imaplib
                    from email.header import decode_header

                    mail = imaplib.IMAP4_SSL("imap.gmail.com")
                    mail.login(user, secret)
                    mail.select("inbox")
                    _, data = mail.search(None, query)
                    mail_ids = data[0].split()[-limit:] if data[0] else []
                    for i in mail_ids:
                        _, msg_data = mail.fetch(i, "(RFC822)")
                        raw = msg_data[0][1]
                        msg = email.message_from_bytes(raw)
                        subject, encoding = decode_header(msg["Subject"])[0] if msg["Subject"] else ("", None)
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8")
                        emails.append(
                            {
                                "id": i.decode(),
                                "from": msg.get("From"),
                                "to": msg.get("To"),
                                "subject": subject,
                                "date": msg.get("Date"),
                                "snippet": (msg.get_payload() or "")[:200]
                                if isinstance(msg.get_payload(), str)
                                else "",
                            }
                        )
                    mail.close()
                    mail.logout()
            except Exception as e:
                emails = [{"error": str(e)}]

        if not emails:
            # simulated fallback
            emails = [
                {
                    "id": "sim-1",
                    "from": "example@lead.com",
                    "subject": "Follow up",
                    "date": "now",
                    "snippet": "Simulated email content...",
                },
            ]

        payload = {"query": query, "limit": limit, "emails": emails}
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
                    f"checked {len(emails)} email(s)",
                    payload,
                    side_effect_class=SideEffectClass.EXTERNAL_READ,
                )
            ],
            summary=f"Gmail check ({len(emails)} results)" if gmail_cred else "Gmail check (simulated)",
        )

    def crm_upsert_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
        inp = GtmCrmUpsertInput.model_validate(inv.input)

        # Item 2: support real CRM via credential (mirror email_send real Gmail logic)
        crm_cred = None
        for k in (inv.action, "gtm.crm_upsert", "external_crm"):
            if k in getattr(ctx, "runtime_credentials", {}):
                crm_cred = ctx.runtime_credentials[k]
                break

        upserted = {
            "record_type": inp.record_type,
            "id": "crm_" + str(ctx.task_id)[:8],
            "data": inp.data,
            "status": "upserted",
        }

        if crm_cred:
            try:
                secret = (
                    getattr(crm_cred, "secret_value", None)
                    if not isinstance(crm_cred, dict)
                    else crm_cred.get("secret_value")
                )
                if secret:
                    # Actual real path: use network_egress with cred for external CRM write
                    trusted = getattr(crm_cred, "trusted_destination_hosts", None) or ("api.crm.example.com",)
                    upsert_url = f"https://{trusted[0]}/v1/upsert"
                    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
                    body = {"record_type": inp.record_type, "data": inp.data}
                    _dest, resp = get_default_network_egress_authority().request(
                        method="POST",
                        url=upsert_url,
                        headers=headers,
                        json_body=body,
                        allowed_hosts=list(trusted),
                        action_name=inv.action,
                        timeout_seconds=10.0,
                    )
                    upserted["status"] = "upserted_real"
                    upserted["credential_used"] = True
                    upserted["real"] = True
                    upserted["real_response"] = {
                        "status_code": resp.status_code,
                        "body_preview": resp.body_text[:300] if resp.body_text else "",
                    }
            except Exception as e:
                upserted["status"] = "error"
                upserted["error"] = str(e)
                upserted["real"] = False

        return ActionResult(
            action=inv.action,
            provider="external_crm",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            output=upserted,
            evidence=[
                _make_evidence(
                    inv.action,
                    "external_crm",
                    ctx,
                    "crm upsert external" + (" (real)" if upserted.get("real") else " (simulated)"),
                    upserted,
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                )
            ],
            records_changed=[str(upserted["id"])],
            summary="External CRM upsert (real via cred)"
            if upserted.get("real")
            else "External CRM upsert (simulated, EXTERNAL_WRITE)",
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
            name="retrieval.hybrid_search",
            handler=retrieval_hybrid_handler,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            provider="local_retrieval",
            input_model=RetrievalHybridInput,
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
            input_model=GtmEmailSendInput,  # loose, handler accepts flexible query dict
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.crm_upsert",
            handler=crm_upsert_handler,
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            provider="external_crm",
            input_model=GtmCrmUpsertInput,
            credential_requirement=CredentialRequirement(
                provider="external_crm",
                credential_type="api_key",
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_WRITE,),
            ),
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

        published = {
            "platform": inp.platform,
            "content": inp.content,
            "post_id": "post_" + str(ctx.task_id)[:8],
            "url": f"https://{inp.platform}.com/post/{str(ctx.task_id)[:8]}",
            "status": "published",
        }

        if social_cred:
            try:
                secret = getattr(social_cred, "secret_value", None)
                if secret:
                    trusted = getattr(social_cred, "trusted_destination_hosts", None) or ("api.social.example.com",)
                    publish_url = f"https://{trusted[0]}/publish"
                    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
                    body = {"platform": inp.platform, "content": inp.content}
                    _dest, resp = get_default_network_egress_authority().request(
                        method="POST",
                        url=publish_url,
                        headers=headers,
                        json_body=body,
                        allowed_hosts=list(trusted),
                        action_name=inv.action,
                        timeout_seconds=10.0,
                    )
                    published["status"] = "published_real"
                    published["credential_used"] = True
                    published["real"] = True
                    published["real_response"] = {
                        "status_code": resp.status_code,
                        "body_preview": resp.body_text[:300] if resp.body_text else "",
                    }
            except Exception as e:
                published["status"] = "error"
                published["error"] = str(e)
                published["real"] = False

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
                    "social published externally" + (" (real)" if published.get("real") else " (simulated)"),
                    published,
                    side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
                )
            ],
            summary="External social publish (real via cred)"
            if published.get("real")
            else "External social publish (simulated, EXTERNAL_PUBLISH, requires approval)",
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
