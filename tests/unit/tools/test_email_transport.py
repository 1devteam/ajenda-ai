from __future__ import annotations

import json

import pytest

from backend.services.tools.email_transport import SmtpConfig, parse_smtp_secret, send_via_smtp


def test_parse_smtp_secret_requires_json_fields() -> None:
    with pytest.raises(ValueError, match="host"):
        parse_smtp_secret(json.dumps({"user": "a", "password": "b"}))


def test_parse_smtp_secret_accepts_valid_payload() -> None:
    config = parse_smtp_secret(
        json.dumps(
            {
                "host": "smtp.example.com",
                "port": 587,
                "user": "sender@example.com",
                "password": "secret",
            }
        )
    )
    assert config.host == "smtp.example.com"
    assert config.port == 587


def test_send_via_smtp_uses_smtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(f"connect:{host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            calls.append("close")

        def starttls(self) -> None:
            calls.append("tls")

        def login(self, user: str, password: str) -> None:
            calls.append(f"login:{user}")

        def sendmail(self, sender: str, recipients: list[str], message: str) -> None:
            calls.append(f"send:{sender}->{recipients[0]}")

    monkeypatch.setattr("backend.services.tools.email_transport.smtplib.SMTP", FakeSMTP)
    outcome = send_via_smtp(
        config=SmtpConfig(
            host="smtp.example.com",
            port=587,
            username="sender@example.com",
            password="secret",
        ),
        to="buyer@example.com",
        subject="Hello",
        body="Body",
    )
    assert outcome.real is True
    assert outcome.status == "sent"
    assert any(call.startswith("send:") for call in calls)
    assert any(call.startswith("login:") for call in calls)
