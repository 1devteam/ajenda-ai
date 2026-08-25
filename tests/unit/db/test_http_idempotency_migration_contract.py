from __future__ import annotations

from pathlib import Path


def test_http_idempotency_receipt_is_control_plane_and_has_atomic_operation_key() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "alembic/versions/0042_add_http_idempotency_receipts.py").read_text(encoding="utf-8")

    assert '"http_idempotency_receipts"' in migration
    assert 'sa.Column("operation_key", sa.String(length=64), nullable=False)' in migration
    assert 'sa.Column("request_fingerprint", sa.String(length=64), nullable=False)' in migration
    assert 'sa.Column("owner_token", sa.String(length=36), nullable=False)' in migration
    assert 'sa.UniqueConstraint("operation_key", name="uq_http_idempotency_operation_key")' in migration
    assert 'sa.Column("response_ciphertext", sa.Text(), nullable=True)' in migration
    assert 'sa.Column("tenant_id"' not in migration
