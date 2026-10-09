"""Shared provider, credential, evidence, and idempotency helpers for GTM actions."""

import base64
from email.mime.text import MIMEText
from typing import Any

from backend.services.tools.schemas import (
    ActionRuntimeContext,
    EvidenceItem,
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
