"""Add secret_ciphertext column to webhook_endpoints.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-07

Changes:
  - webhook_endpoints.secret_ciphertext (TEXT, nullable)
      Stores the Fernet-encrypted plaintext HMAC signing secret.
      When present, the WebhookDispatchService decrypts this at delivery time
      and uses the plaintext as the HMAC-SHA256 key, allowing tenants to verify
      signatures using their plaintext secret.

      NULL for endpoints created before this migration (legacy bcrypt-hash signing).
      New endpoints created after this migration will always have this column set.

Migration note:
  Existing webhook_endpoints rows will have secret_ciphertext = NULL. They will
  continue to use the legacy bcrypt-hash signing path until they are re-registered
  or a backfill job encrypts their secrets. The backfill is not included here
  because the plaintext secrets are not stored — only the bcrypt hashes are.
  Operators should ask tenants to re-register endpoints to get verifiable signatures.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_endpoints",
        sa.Column(
            "secret_ciphertext",
            sa.Text(),
            nullable=True,
            comment=(
                "Fernet-encrypted plaintext HMAC signing secret. "
                "Decrypted at delivery time to produce a verifiable HMAC signature. "
                "NULL for endpoints created before migration 0009."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "secret_ciphertext")
