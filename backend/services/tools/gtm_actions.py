"""GTM actions for lead enrichment and email drafting (PR6 expansion).

Core actions implemented with evidence, side-effect classification, and credential requirements for high-risk external.
Local/simulated providers for proof-of-concept and CI; production uses credential injection + egress authority.
"""

from __future__ import annotations

import base64
import json
import uuid
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

from backend.repositories.retrieval_contract_repository import RetrievalContractRepository
from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.network_egress import get_default_network_egress_authority
from backend.services.plugins.crm_client import default_crm_client, is_live_external_crm_result
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.email_transport import (
    credential_transport_mode,
    parse_smtp_secret,
    send_via_smtp,
)
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
    RetrievalHybridInput,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)


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
        gmail_cred = _get_runtime_credential(
            ctx,
            action=inv.action,
            aliases=("gtm.email_send", "external_email"),
        )
        body_text = inp.body or str(inp.context.get("body", ""))

        sent: dict[str, Any] = {
            "to": inp.to,
            "subject": inp.subject,
            "body": body_text,
            "status": "simulated",
            "context": inp.context,
            "real": False,
            "reason": "no_runtime_credential",
        }

        secret = _credential_secret(gmail_cred)
        if secret:
            transport = credential_transport_mode(gmail_cred)
            try:
                if transport == "smtp":
                    smtp_config = parse_smtp_secret(secret)
                    smtp_result = send_via_smtp(
                        config=smtp_config,
                        to=inp.to,
                        subject=inp.subject,
                        body=body_text,
                    )
                    sent["provider"] = smtp_result.provider
                    sent["status"] = smtp_result.status
                    sent["real"] = smtp_result.real
                    if smtp_result.error:
                        sent["error"] = smtp_result.error
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
                        json_body=_gmail_api_send_payload(to=inp.to, subject=inp.subject, body=body_text),
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
                    "External email sent via Gmail"
                    if sent.get("real")
                    else "External email not sent (simulated; no outbound effect)",
                    sent,
                    side_effect_class=SideEffectClass.EXTERNAL_SEND,
                )
            ],
            summary="External email sent via Gmail"
            if sent.get("real")
            else "External email not sent (simulated; no outbound effect)",
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
        if secret:
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
            except Exception as e:
                emails = [{"error": str(e)}]

        if not emails:
            emails = [
                {
                    "id": "sim-1",
                    "from": "example@lead.com",
                    "subject": "Follow up",
                    "date": "now",
                    "snippet": "Simulated email content...",
                },
            ]

        payload = {"query": inp.query, "limit": inp.limit, "emails": emails}
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
        side_effect = SideEffectClass.INTERNAL_WRITE
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
            input_model=GtmEmailCheckInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.crm_upsert",
            handler=crm_upsert_handler,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
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
