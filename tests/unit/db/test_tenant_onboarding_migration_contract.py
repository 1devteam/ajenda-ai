"""Migration contract checks for Phase 1A onboarding schema."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_onboarding_migrations_have_single_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0036_composition_thread"]
    assert len(heads[0]) <= 32


def test_tenant_members_migration_matches_domain_contract() -> None:
    migration = Path("alembic/versions/0028_add_tenant_members.py").read_text(encoding="utf-8")
    model = Path("backend/domain/tenant_member.py").read_text(encoding="utf-8")

    assert "tenant_members" in migration
    assert "email_canonical" in migration
    assert "pending_verification" in migration
    assert '__tablename__ = "tenant_members"' in model
    assert "email_canonical" in model


def test_api_key_bootstrap_migration_matches_orm_fields() -> None:
    migration = Path("alembic/versions/0029_extend_api_key_records_bootstrap.py").read_text(encoding="utf-8")
    model = Path("backend/domain/api_key_record.py").read_text(encoding="utf-8")

    assert "purpose" in migration
    assert "expires_at" in migration
    assert "roles_json" in migration
    assert "purpose: Mapped[str]" in model
    assert "expires_at: Mapped[datetime | None]" in model
    assert "roles_json: Mapped[list[str]]" in model
