"""Migration contract checks for customer OIDC auth tables."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_customer_auth_migration_is_current_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0049_continuous_assurance"]
    assert len(heads[0]) <= 32


def test_customer_auth_migration_matches_domain_contract() -> None:
    migration = Path("alembic/versions/0032_add_customer_auth_tables.py").read_text(encoding="utf-8")
    intent_model = Path("backend/domain/oidc_login_intent.py").read_text(encoding="utf-8")
    session_model = Path("backend/domain/customer_auth_session.py").read_text(encoding="utf-8")

    assert "oidc_login_intents" in migration
    assert "customer_auth_sessions" in migration
    assert "code_challenge" in migration
    assert "refresh_token_hash" in migration
    assert '__tablename__ = "oidc_login_intents"' in intent_model
    assert '__tablename__ = "customer_auth_sessions"' in session_model
