from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_retrieval_contract_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0016_retrieval_contracts"]
    assert len(heads[0]) <= 32


def test_retrieval_contract_migration_contains_tenant_indexes_jsonb_and_rls_policies() -> None:
    migration = Path("alembic/versions/0016_retrieval_contracts.py").read_text(encoding="utf-8")

    assert "retrieval_contracts" in migration
    assert "ix_retrieval_contracts_tenant_id" in migration
    assert "ix_retrieval_contracts_mission_id" in migration
    assert "postgresql.JSONB" in migration
    assert "retrieval_request" in migration
    assert "strategy_metadata" in migration
    assert "retrieval_filters" in migration
    assert "governance_constraints" in migration
    assert "returned_memory_references" in migration
    assert "trust_signal" in migration
    assert "provenance_metadata" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_retrieval_contract_isolation" in migration
    assert "def downgrade" in migration
