from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.services.light_crm.records import LightCrmRecordService
from backend.services.light_crm.schemas import (
    STALE_ACTIVITY_DAYS,
    activity_payload,
    normalize_email,
    normalize_stage,
)


def _mission_id(ctx: dict[str, Any]) -> str | None:
    value = ctx.get("mission_id")
    return str(value) if value else None


def _task_id(ctx: dict[str, Any]) -> str | None:
    value = ctx.get("task_id")
    return str(value) if value else None


def on_email_sent(
    *,
    session: Session,
    tenant_id: str,
    to: str,
    subject: str,
    artifact_id: str | None,
    sent_real: bool,
    mission_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    crm = LightCrmRecordService(session=session)
    email = normalize_email(to)
    if not email:
        return {"logged": False, "reason": "missing_recipient_email"}

    contact_id = crm.find_record_id_by_field(
        tenant_id=tenant_id,
        record_type="contact",
        field="email",
        value=email,
    )
    contact: dict[str, Any]
    if contact_id:
        existing = crm.read_record(tenant_id=tenant_id, record_type="contact", record_id=contact_id)
        contact = existing or {"id": contact_id, "email": email}
    else:
        contact = crm.identity_upsert(
            tenant_id=tenant_id,
            record_type="contact",
            data={"email": email, "source": "workflow:email_sent"},
        )

    activity = crm.log_activity(
        tenant_id=tenant_id,
        payload=activity_payload(
            activity_type="email_sent",
            subject=subject or "Outbound email",
            body=f"Email sent to {email}" if sent_real else f"Email send recorded for {email} (simulated)",
            related_type="contact",
            related_id=str(contact["id"]),
            mission_id=mission_id,
            task_id=task_id,
            artifact_id=artifact_id,
            source_action="gtm.email_send",
            metadata={"real": sent_real},
        ),
    )

    opportunity = crm.ensure_opportunity_for_contact(tenant_id=tenant_id, contact=contact)
    stage_changed = None
    if opportunity is not None and str(opportunity.get("stage")) in {"new", "qualified", "discovery"}:
        updated = crm.identity_upsert(
            tenant_id=tenant_id,
            record_type="opportunity",
            data={**opportunity, "stage": "outreach"},
        )
        crm.log_activity(
            tenant_id=tenant_id,
            payload=activity_payload(
                activity_type="stage_changed",
                subject="Stage moved to outreach",
                body="Automated stage bump after governed email send.",
                related_type="opportunity",
                related_id=str(updated["id"]),
                mission_id=mission_id,
                task_id=task_id,
                source_action="wf-send-bump-stage",
                metadata={"from": opportunity.get("stage"), "to": "outreach"},
            ),
        )
        stage_changed = "outreach"

    return {
        "logged": True,
        "contact_id": contact.get("id"),
        "activity_id": activity.get("id"),
        "opportunity_id": opportunity.get("id") if opportunity else None,
        "stage_changed": stage_changed,
    }


def on_draft_approved(
    *,
    session: Session,
    tenant_id: str,
    artifact_id: str,
    artifact_content: dict[str, Any] | None,
    note: str | None = None,
) -> dict[str, Any]:
    crm = LightCrmRecordService(session=session)
    content = artifact_content or {}
    recipient = normalize_email(content.get("to") or content.get("recipient"))
    if not recipient:
        return {"logged": False, "reason": "artifact_missing_recipient"}

    contact = crm.identity_upsert(
        tenant_id=tenant_id,
        record_type="contact",
        data={"email": recipient, "source": "workflow:draft_approved"},
    )
    activity = crm.log_activity(
        tenant_id=tenant_id,
        payload=activity_payload(
            activity_type="draft_approved",
            subject=str(content.get("subject") or "Draft approved"),
            body=note or "Review queue approved artifact for send.",
            related_type="contact",
            related_id=str(contact["id"]),
            artifact_id=artifact_id,
            source_action="review_queue.approve",
        ),
    )
    return {"logged": True, "contact_id": contact.get("id"), "activity_id": activity.get("id")}


def complete_internal_crm_upsert(
    *,
    session: Session,
    tenant_id: str,
    record_type: str,
    data: dict[str, Any],
    mission_id: str | None = None,
    task_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Canonical internal CRM upsert with identity dedupe and workflow timeline hooks."""
    crm = LightCrmRecordService(session=session)
    saved = crm.identity_upsert(tenant_id=tenant_id, record_type=record_type, data=data)
    on_crm_upsert_completed(
        session=session,
        tenant_id=tenant_id,
        record_type=record_type,
        record=saved,
        mission_id=mission_id,
        task_id=task_id,
    )
    if commit:
        session.commit()
    return saved


def on_crm_upsert_completed(
    *,
    session: Session,
    tenant_id: str,
    record_type: str,
    record: dict[str, Any],
    mission_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    crm = LightCrmRecordService(session=session)
    record_id = str(record.get("id") or "")
    if not record_id:
        return {"logged": False, "reason": "missing_record_id"}

    crm.log_activity(
        tenant_id=tenant_id,
        payload=activity_payload(
            activity_type="record_upserted",
            subject=f"{record_type} upserted",
            body=f"Governed CRM upsert for {record_type} {record_id}.",
            related_type=record_type,
            related_id=record_id,
            mission_id=mission_id,
            task_id=task_id,
            source_action="gtm.crm_upsert",
        ),
    )

    opportunity_id = None
    if record_type == "contact":
        opportunity = crm.ensure_opportunity_for_contact(tenant_id=tenant_id, contact=record)
        if opportunity is not None:
            opportunity_id = opportunity.get("id")

    if record_type == "opportunity":
        stage = normalize_stage(record.get("stage"))
        if stage == "proposal":
            task = crm.identity_upsert(
                tenant_id=tenant_id,
                record_type="task",
                data={
                    "title": f"Send proposal for {record.get('name', record_id)}",
                    "status": "open",
                    "due_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
                    "related_type": "opportunity",
                    "related_id": record_id,
                    "source": "wf-stage-proposal-task",
                },
            )
            crm.log_activity(
                tenant_id=tenant_id,
                payload=activity_payload(
                    activity_type="task_created",
                    subject="Follow-up task created",
                    body=str(task.get("title") or "Proposal follow-up"),
                    related_type="opportunity",
                    related_id=record_id,
                    source_action="wf-stage-proposal-task",
                    metadata={"task_id": task.get("id")},
                ),
            )

    return {"logged": True, "record_id": record_id, "opportunity_id": opportunity_id}


def workflow_suggestions(*, session: Session, tenant_id: str) -> list[dict[str, Any]]:
    crm = LightCrmRecordService(session=session)
    suggestions: list[dict[str, Any]] = []
    opportunities = crm.list_records(tenant_id=tenant_id, record_type="opportunity", limit=50)
    cutoff = datetime.now(UTC) - timedelta(days=STALE_ACTIVITY_DAYS)

    for opportunity in opportunities:
        opp_id = str(opportunity.get("id") or "")
        if not opp_id:
            continue
        timeline = crm.list_timeline(tenant_id=tenant_id, record_type="opportunity", record_id=opp_id, limit=1)
        last_at = None
        if timeline:
            try:
                last_at = datetime.fromisoformat(str(timeline[0].get("occurred_at")))
            except ValueError:
                last_at = None
        if last_at is not None and last_at >= cutoff:
            continue
        if str(opportunity.get("stage")) in {"closed_won", "closed_lost"}:
            continue
        suggestions.append(
            {
                "suggestion_id": f"stale-{opp_id}",
                "reason": "no_recent_activity",
                "mission_action": "sales.draft_followup",
                "title": f"Follow up on {opportunity.get('name', opp_id)}",
                "description": f"No activity in {STALE_ACTIVITY_DAYS}+ days — draft a follow-up.",
                "related_type": "opportunity",
                "related_id": opp_id,
            }
        )
    return suggestions[:5]
