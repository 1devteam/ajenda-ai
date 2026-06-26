from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any


@dataclass(slots=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    use_tls: bool = True
    from_address: str | None = None


@dataclass(slots=True)
class EmailSendOutcome:
    provider: str
    real: bool
    status: str
    error: str | None = None


def parse_smtp_secret(secret_value: str) -> SmtpConfig:
    try:
        payload = json.loads(secret_value)
    except json.JSONDecodeError as exc:
        raise ValueError("smtp credential secret must be JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("smtp credential secret must be a JSON object")
    host = str(payload.get("host", "")).strip()
    username = str(payload.get("user", payload.get("username", ""))).strip()
    password = str(payload.get("password", "")).strip()
    if not host or not username or not password:
        raise ValueError("smtp credential requires host, user/username, and password")
    port = int(payload.get("port", 587))
    use_tls = bool(payload.get("use_tls", True))
    from_address = payload.get("from")
    return SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        use_tls=use_tls,
        from_address=str(from_address).strip() if from_address else None,
    )


def send_via_smtp(*, config: SmtpConfig, to: str, subject: str, body: str) -> EmailSendOutcome:
    message = MIMEText(body or " ")
    sender = config.from_address or config.username
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    try:
        with smtplib.SMTP(config.host, config.port, timeout=10) as client:
            if config.use_tls:
                client.starttls()
            client.login(config.username, config.password)
            client.sendmail(sender, [to], message.as_string())
        return EmailSendOutcome(provider="smtp", real=True, status="sent")
    except Exception as exc:
        return EmailSendOutcome(provider="smtp", real=False, status="error", error=str(exc))


def credential_transport_mode(
    material: Any,
) -> str:
    if material is None:
        return "none"
    credential_type = None
    if isinstance(material, dict):
        credential_type = material.get("credential_type")
        reference = material.get("reference")
        if credential_type is None and isinstance(reference, dict):
            credential_type = reference.get("credential_type")
    else:
        credential_type = material.reference.credential_type
    if credential_type == "smtp":
        return "smtp"
    return "gmail_api"
