from __future__ import annotations

from typing import Any

from backend.services.business_context_resolver import BusinessContext, resolve_business_context
from backend.services.document_artifacts import SUPPORTED_ARTIFACT_TYPES, persist_artifact
from backend.services.llm.contracts import LlmGenerateRequest
from backend.services.llm.factory import generate_text
from backend.services.tools.schemas import ActionRuntimeContext


def _products_line(context: BusinessContext) -> str:
    if context.products_services:
        return ", ".join(context.products_services)
    return "our services"


def _company_line(context: BusinessContext) -> str:
    return context.business_name or context.company or "our team"


def _template_pitch_email(*, recipient: str, topic: str, tone: str, biz: BusinessContext) -> dict[str, str]:
    company = _company_line(biz)
    products = _products_line(biz)
    body = (
        f"Hi,\n\n"
        f"I'm reaching out from {company} regarding {topic}. "
        f"We help teams with {products}.\n\n"
        f"Would you be open to a short conversation to explore fit?\n\n"
        f"Best,\n{company}"
    )
    return {
        "to": recipient,
        "subject": f"{topic} — {company}",
        "body": body,
        "tone": tone,
        "generation_mode": "template",
    }


def _template_document_body(*, artifact_type: str, topic: str, tone: str, biz: BusinessContext) -> dict[str, str]:
    company = _company_line(biz)
    products = _products_line(biz)
    body = (
        f"{topic}\n\n"
        f"{company} helps teams with {products}. "
        f"This {artifact_type.replace('_', ' ')} summarizes fit, outcomes, and a practical next step.\n\n"
        f"Tone: {tone}."
    )
    return {"body": body, "tone": tone, "generation_mode": "template"}


def _template_follow_up(*, recipient_name: str, topic: str, tone: str, biz: BusinessContext) -> dict[str, str]:
    company = _company_line(biz)
    draft = (
        f"Hi {recipient_name},\n\n"
        f"Following up on {topic}. "
        f"I wanted to share a practical next step we can take together.\n\n"
        f"Best,\n{company}"
    )
    return {
        "draft": draft,
        "tone": tone,
        "generation_mode": "template",
    }


def _llm_system_prompt(*, artifact_type: str) -> str:
    return (
        "You are Ajenda's clerical brain drafting customer-facing copy. "
        "Write concise, accurate, professional text. "
        "Do not invent product claims beyond provided business context. "
        f"Artifact type: {artifact_type}."
    )


def _llm_user_prompt(
    *,
    artifact_type: str,
    topic: str,
    tone: str,
    recipient: str | None,
    recipient_name: str | None,
    extra_context: dict[str, Any],
    biz: BusinessContext,
) -> str:
    lines = [
        f"Artifact type: {artifact_type}",
        f"Topic: {topic}",
        f"Tone: {tone}",
    ]
    if recipient:
        lines.append(f"Recipient email: {recipient}")
    if recipient_name:
        lines.append(f"Recipient name: {recipient_name}")
    if biz.business_name:
        lines.append(f"Business name: {biz.business_name}")
    if biz.products_services:
        lines.append(f"Products/services: {', '.join(biz.products_services)}")
    if biz.target_customers:
        lines.append(f"Target customers: {', '.join(biz.target_customers)}")
    if biz.operator_notes:
        lines.append(f"Operator notes: {biz.operator_notes}")
    if extra_context:
        lines.append(f"Mission context: {extra_context}")
    if artifact_type == "pitch_email":
        lines.append("Return JSON with keys: subject, body.")
    elif artifact_type == "follow_up":
        lines.append("Return plain-text follow-up message body only.")
    else:
        lines.append("Return plain-text document body only.")
    return "\n".join(lines)


def _parse_pitch_from_llm(text: str, *, recipient: str, topic: str, tone: str, biz: BusinessContext) -> dict[str, str]:
    import json

    company = _company_line(biz)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            subject = str(payload.get("subject") or f"{topic} — {company}").strip()
            body = str(payload.get("body") or text).strip()
            return {
                "to": recipient,
                "subject": subject,
                "body": body,
                "tone": tone,
                "generation_mode": "llm",
            }
    except json.JSONDecodeError:
        pass
    return {
        "to": recipient,
        "subject": f"{topic} — {company}",
        "body": text.strip(),
        "tone": tone,
        "generation_mode": "llm",
    }


def generate_and_persist_draft(
    ctx: ActionRuntimeContext,
    *,
    artifact_type: str,
    topic: str,
    tone: str,
    recipient: str | None = None,
    recipient_name: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = artifact_type.strip().lower()
    if normalized_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ValueError(f"unsupported artifact_type: {artifact_type}")

    biz = resolve_business_context(ctx)
    context = extra_context or {}
    llm_result = generate_text(
        request=LlmGenerateRequest(
            system_prompt=_llm_system_prompt(artifact_type=normalized_type),
            user_prompt=_llm_user_prompt(
                artifact_type=normalized_type,
                topic=topic,
                tone=tone,
                recipient=recipient,
                recipient_name=recipient_name,
                extra_context=context,
                biz=biz,
            ),
        )
    )

    if llm_result.used_llm:
        if normalized_type == "pitch_email":
            content = _parse_pitch_from_llm(
                llm_result.text,
                recipient=recipient or "lead@example.com",
                topic=topic,
                tone=tone,
                biz=biz,
            )
        elif normalized_type == "follow_up":
            content = {
                "draft": llm_result.text.strip(),
                "tone": tone,
                "generation_mode": "llm",
            }
        else:
            content = {
                "body": llm_result.text.strip(),
                "tone": tone,
                "generation_mode": "llm",
            }
    elif normalized_type == "pitch_email":
        content = _template_pitch_email(
            recipient=recipient or "lead@example.com",
            topic=topic,
            tone=tone,
            biz=biz,
        )
    elif normalized_type == "follow_up":
        content = _template_follow_up(
            recipient_name=recipient_name or "there",
            topic=topic,
            tone=tone,
            biz=biz,
        )
    elif normalized_type in {"capability_resume", "roi_brief"}:
        content = _template_document_body(
            artifact_type=normalized_type,
            topic=topic,
            tone=tone,
            biz=biz,
        )
    else:
        raise ValueError(
            f"artifact_type {artifact_type!r} requires LLM configuration; template fallback is unavailable"
        )

    session_factory = ctx.session_factory
    if session_factory is None:
        payload: dict[str, Any] = dict(content)
        payload["artifact_id"] = None
        payload["provider"] = llm_result.provider
        payload["model"] = llm_result.model
        return payload

    session = session_factory()
    try:
        saved = persist_artifact(
            session,
            tenant_id=ctx.tenant_id,
            artifact_type=normalized_type,
            content=content,
            metadata={
                "topic": topic,
                "tone": tone,
                "provider": llm_result.provider,
                "model": llm_result.model,
                "used_llm": llm_result.used_llm,
                "business_context_source": biz.source,
            },
            review_status="pending",
            mission_id=str(ctx.mission_id) if ctx.mission_id else None,
            task_id=str(ctx.task_id) if ctx.task_id else None,
        )
        session.commit()
    finally:
        session.close()

    output = {
        **content,
        "artifact_id": saved["artifact_id"],
        "provider": llm_result.provider,
        "model": llm_result.model,
    }
    return output
