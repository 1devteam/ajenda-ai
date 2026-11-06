"""GTM email/social draft-generation handlers."""

import hashlib
from typing import Any

from backend.services.draft_generation import generate_and_persist_draft
from backend.services.tools.gtm_action_common import _make_evidence
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    GtmEmailDraftInput,
    GtmSocialDraftInput,
    SideEffectClass,
    ToolInvocation,
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


def social_draft_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    inp = GtmSocialDraftInput.model_validate(inv.input)
    context = dict(inp.context)
    requested = max(1, min(int(context.get("draft_count") or 1), 20))
    upstream = context.get("upstream")
    report = upstream.get("research_report") if isinstance(upstream, dict) else None
    rows = report.get("comparison") if isinstance(report, dict) else None
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    posts: list[dict[str, Any]] = []
    angles = ("what we learned", "services and fit", "a useful takeaway")
    for index in range(requested):
        row = rows[index % len(rows)] if rows else {}
        company = str(row.get("company") or "the company").strip()
        summary_text = " ".join(str(row.get("summary") or "").split())
        facts = [
            str(row.get("product_description") or "").strip(),
            "Services: " + ", ".join(str(value).strip() for value in row.get("services", []) if str(value).strip())
            if isinstance(row.get("services"), list) and row.get("services")
            else "",
            "Differentiators: "
            + ", ".join(str(value).strip() for value in row.get("differentiators", []) if str(value).strip())
            if isinstance(row.get("differentiators"), list) and row.get("differentiators")
            else "",
        ]
        profile_text = " ".join(value for value in facts if value)
        summary_text = profile_text or summary_text
        source = next((str(item).strip() for item in (row.get("sources") or []) if str(item).strip()), "")
        if not summary_text or summary_text == "No supported summary available.":
            continue
        angle = angles[index % len(angles)]
        source_suffix = f" Source: {source}" if source else ""
        prefix = f"{company} — {angle}: "
        excerpt_limit = max(20, 280 - len(prefix) - len(source_suffix) - 1)
        excerpt = summary_text[: min(150, excerpt_limit)].rstrip()
        content = f"{prefix}{excerpt}.{source_suffix}"[:280]
        posts.append(
            {
                "platform": inp.platform,
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "status": "draft",
                "real": False,
                "source_urls": [source] if source else [],
                "context": {**context, "angle": angle, "evidence_backed": True},
            }
        )
    output: dict[str, Any] = {
        "platform": inp.platform,
        "content": posts[0]["content"] if posts else inp.content,
        "content_hash": hashlib.sha256((posts[0]["content"] if posts else inp.content).encode("utf-8")).hexdigest(),
        "status": "draft",
        "real": False,
        "context": context,
        "social_drafts": posts,
        "draft_count": len(posts),
    }
    summary = f"Prepared {len(posts)} evidence-backed social draft(s) for {inp.platform}"
    return ActionResult(
        action=inv.action,
        provider="local_gtm",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[_make_evidence(inv.action, "local_gtm", ctx, summary, output)],
        summary=summary,
    )
