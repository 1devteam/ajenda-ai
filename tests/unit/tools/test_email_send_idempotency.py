"""Unit tests for SMTP email-send claim-before-send protection."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from backend.domain.email_send_idempotency import (
    EMAIL_SEND_CLAIM_STATUS_CLAIMING,
    EMAIL_SEND_CLAIM_STATUS_COMPLETED,
    EmailSendIdempotencyReceipt,
)
from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.email_send_idempotency import (
    claim_smtp_send,
    complete_smtp_send,
    release_smtp_send,
)
from backend.services.tools.email_transport import SmtpConfig
from backend.services.tools.gtm_actions import register_gtm_actions
from backend.services.tools.schemas import (
    ActionRuntimeContext,
    CredentialReference,
    RuntimeCredentialMaterial,
    ToolInvocation,
)


class _InMemoryIdempotencyRepo:
    """Stand-in for EmailSendIdempotencyRepository for pure unit tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    def try_claim(self, *, tenant_id: str, action: str, idempotency_key: str) -> tuple[str, dict[str, Any] | None]:
        key = (tenant_id, action, idempotency_key)
        existing = self.rows.get(key)
        if existing is None:
            self.rows[key] = {"status": EMAIL_SEND_CLAIM_STATUS_CLAIMING, "result_payload": None}
            return "newly_claimed", None
        if existing["status"] == EMAIL_SEND_CLAIM_STATUS_COMPLETED:
            return "replayed", dict(existing["result_payload"] or {})
        return "in_flight", None

    def complete(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        result_payload: dict[str, Any],
    ) -> None:
        key = (tenant_id, action, idempotency_key)
        self.rows[key] = {
            "status": EMAIL_SEND_CLAIM_STATUS_COMPLETED,
            "result_payload": dict(result_payload),
        }

    def release(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        error_detail: str | None = None,
    ) -> None:
        _ = error_detail
        key = (tenant_id, action, idempotency_key)
        row = self.rows.get(key)
        if row and row["status"] == EMAIL_SEND_CLAIM_STATUS_CLAIMING:
            del self.rows[key]


def _session_factory_for_repo(repo: _InMemoryIdempotencyRepo):
    session = MagicMock()

    def factory():
        return session

    def repo_ctor(_session):
        return repo

    return factory, repo_ctor


def test_claim_requires_idempotency_key() -> None:
    result = claim_smtp_send(
        session_factory=lambda: MagicMock(),
        tenant_id="t1",
        action="gtm.email_send",
        idempotency_key=None,
    )
    assert result.decision == "rejected"
    assert result.error is not None
    assert "idempotency_key" in result.error


def test_claim_requires_session_factory() -> None:
    result = claim_smtp_send(
        session_factory=None,
        tenant_id="t1",
        action="gtm.email_send",
        idempotency_key="k1",
    )
    assert result.decision == "rejected"
    assert "session_factory" in (result.error or "")


def test_claim_complete_replay_flow() -> None:
    repo = _InMemoryIdempotencyRepo()
    factory, repo_ctor = _session_factory_for_repo(repo)

    with patch(
        "backend.services.tools.email_send_idempotency.EmailSendIdempotencyRepository",
        side_effect=repo_ctor,
    ):
        first = claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-1",
        )
        assert first.decision == "newly_claimed"

        complete_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-1",
            result_payload={"status": "sent", "real": True, "provider": "smtp"},
        )

        second = claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-1",
        )
        assert second.decision == "replayed"
        assert second.cached_output is not None
        assert second.cached_output["status"] == "sent"


def test_in_flight_blocks_second_claim() -> None:
    repo = _InMemoryIdempotencyRepo()
    factory, repo_ctor = _session_factory_for_repo(repo)

    with patch(
        "backend.services.tools.email_send_idempotency.EmailSendIdempotencyRepository",
        side_effect=repo_ctor,
    ):
        first = claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-2",
        )
        assert first.decision == "newly_claimed"
        second = claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-2",
        )
        assert second.decision == "in_flight"


def test_release_allows_reclaim() -> None:
    repo = _InMemoryIdempotencyRepo()
    factory, repo_ctor = _session_factory_for_repo(repo)

    with patch(
        "backend.services.tools.email_send_idempotency.EmailSendIdempotencyRepository",
        side_effect=repo_ctor,
    ):
        claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-3",
        )
        release_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-3",
            error_detail="smtp down",
        )
        again = claim_smtp_send(
            session_factory=factory,
            tenant_id="t1",
            action="gtm.email_send",
            idempotency_key="idem-3",
        )
        assert again.decision == "newly_claimed"


def _smtp_context(*, session_factory=None) -> ActionRuntimeContext:
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
        session_factory=session_factory,
    )
    context.runtime_credentials = {
        "gtm.email_send": RuntimeCredentialMaterial(
            reference=CredentialReference(
                credential_id="smtp-cred-1",
                provider="external_email",
                credential_type="smtp",
            ),
            secret_value=('{"host":"smtp.example.com","port":587,"user":"sender@example.com","password":"secret"}'),
        )
    }
    return context


def test_gtm_email_send_smtp_rejects_without_idempotency_key() -> None:
    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    result = handler(
        ToolInvocation(
            action="gtm.email_send",
            input={"to": "buyer@example.com", "subject": "Hi", "body": "Body"},
        ),
        _smtp_context(session_factory=lambda: MagicMock()),
    )
    assert result.output["real"] is False
    assert result.output["status"] == "error"
    assert "idempotency_key" in result.output["error"]


def test_gtm_email_send_smtp_claims_before_send_and_replays() -> None:
    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    repo = _InMemoryIdempotencyRepo()
    factory, repo_ctor = _session_factory_for_repo(repo)
    context = _smtp_context(session_factory=factory)

    send_calls: list[str] = []

    def fake_send(**kwargs):
        from backend.services.tools.email_transport import EmailSendOutcome

        send_calls.append(kwargs.get("to", ""))
        return EmailSendOutcome(provider="smtp", real=True, status="sent")

    with (
        patch(
            "backend.services.tools.email_send_idempotency.EmailSendIdempotencyRepository",
            side_effect=repo_ctor,
        ),
        patch("backend.services.tools.gtm_actions.send_via_smtp", side_effect=fake_send),
        patch(
            "backend.services.tools.gtm_actions.parse_smtp_secret",
            return_value=SmtpConfig(
                host="smtp.example.com",
                port=587,
                username="sender@example.com",
                password="secret",
            ),
        ),
    ):
        first = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "buyer@example.com", "subject": "Hi", "body": "Body"},
                idempotency_key="smtp-idem-1",
            ),
            context,
        )
        second = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "buyer@example.com", "subject": "Hi", "body": "Body"},
                idempotency_key="smtp-idem-1",
            ),
            context,
        )

    assert first.output["real"] is True
    assert first.output["status"] == "sent"
    assert first.output["idempotency_key"] == "smtp-idem-1"
    assert second.output["real"] is True
    assert second.output.get("idempotency_replayed") is True
    assert len(send_calls) == 1


def test_email_send_idempotency_receipt_model_constants() -> None:
    assert EMAIL_SEND_CLAIM_STATUS_CLAIMING == "claiming"
    assert EMAIL_SEND_CLAIM_STATUS_COMPLETED == "completed"
    assert EmailSendIdempotencyReceipt.__tablename__ == "email_send_idempotency_receipts"
