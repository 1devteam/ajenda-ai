from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_email_send_idempotency_migration_is_current_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0038_knowledge_retrieval"]
    assert len(heads[0]) <= 32


def test_email_send_idempotency_migration_matches_orm_fields() -> None:
    migration = Path("alembic/versions/0034_add_email_send_idempotency_receipts.py").read_text(encoding="utf-8")
    model = Path("backend/domain/email_send_idempotency.py").read_text(encoding="utf-8")

    assert "email_send_idempotency_receipts" in migration
    assert "idempotency_key" in migration
    assert "result_payload" in migration
    assert "uq_email_send_idempotency_tenant_action_key" in migration
    assert "EmailSendIdempotencyReceipt" in model
    assert "email_send_idempotency_receipts" in model
