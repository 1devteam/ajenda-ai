from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_provider_runtime_credential_migration_is_current_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0036_composition_thread"]
    assert len(heads[0]) <= 32


def test_provider_runtime_credential_migration_matches_runtime_boundary_contract() -> None:
    migration = Path("alembic/versions/0024_add_provider_runtime_credentials.py").read_text(encoding="utf-8")
    model = Path("backend/domain/provider_runtime_credential.py").read_text(encoding="utf-8")

    assert "provider_runtime_credentials" in migration
    assert "secret_ciphertext" in migration
    assert "secret_value" not in migration
    assert "trusted_destination_hosts" in migration
    assert "allowed_actions" in migration
    assert "allowed_side_effect_classes" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_provider_runtime_credential_isolation" in migration
    assert "admin_bypass" in migration
    assert "secret_ciphertext: Mapped[str]" in model
    assert "secret_value" not in model
