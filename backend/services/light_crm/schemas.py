from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

ActivityType = Literal[
    "email_sent",
    "draft_approved",
    "record_upserted",
    "stage_changed",
    "stale_warning",
    "task_created",
    "note",
]

PIPELINE_STAGES: tuple[str, ...] = (
    "new",
    "qualified",
    "discovery",
    "outreach",
    "proposal",
    "negotiation",
    "closed_won",
    "closed_lost",
)

DEFAULT_OPPORTUNITY_STAGE = "discovery"
STALE_ACTIVITY_DAYS = 14


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def normalize_domain(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    return cleaned or None


def normalize_stage(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace(" ", "_")
    if cleaned in PIPELINE_STAGES:
        return cleaned
    return cleaned or None


def enrich_contact_data(data: dict[str, Any]) -> dict[str, Any]:
    record = dict(data)
    email = normalize_email(record.get("email"))
    if email:
        record["email"] = email
    if isinstance(record.get("firstname"), str) or isinstance(record.get("lastname"), str):
        first = str(record.get("firstname") or "").strip()
        last = str(record.get("lastname") or "").strip()
        full = " ".join(part for part in (first, last) if part).strip()
        if full and not record.get("name"):
            record["name"] = full
    company = str(record.get("company") or record.get("account_name") or "").strip()
    if company and not record.get("account_name"):
        record["account_name"] = company
    return record


def enrich_account_data(data: dict[str, Any]) -> dict[str, Any]:
    record = dict(data)
    domain = normalize_domain(record.get("domain") or record.get("website"))
    if domain:
        record["domain"] = domain
    name = str(record.get("name") or record.get("company") or "").strip()
    if name:
        record["name"] = name
    return record


def enrich_opportunity_data(data: dict[str, Any]) -> dict[str, Any]:
    record = dict(data)
    stage = normalize_stage(record.get("stage")) or DEFAULT_OPPORTUNITY_STAGE
    record["stage"] = stage
    if not record.get("name"):
        account = str(record.get("account_name") or record.get("company") or "Opportunity").strip()
        record["name"] = f"{account} opportunity"
    return record


def activity_payload(
    *,
    activity_type: ActivityType,
    subject: str,
    body: str,
    related_type: str,
    related_id: str,
    mission_id: str | None = None,
    task_id: str | None = None,
    artifact_id: str | None = None,
    source_action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": activity_type,
        "subject": subject,
        "body": body,
        "related_type": related_type,
        "related_id": related_id,
        "occurred_at": utc_now_iso(),
    }
    if mission_id:
        payload["mission_id"] = mission_id
    if task_id:
        payload["task_id"] = task_id
    if artifact_id:
        payload["artifact_id"] = artifact_id
    if source_action:
        payload["source_action"] = source_action
    if metadata:
        payload["metadata"] = metadata
    return payload
