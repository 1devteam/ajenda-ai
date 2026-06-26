from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_evidence_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0033_tenant_internal_records"]
    assert len(heads[0]) <= 32


def test_evidence_migration_contains_tenant_indexes_and_rls_policies() -> None:
    migration = Path("alembic/versions/0013_evidence_contracts.py").read_text(encoding="utf-8")

    assert "evidence_records" in migration
    assert "ix_evidence_records_tenant_id" in migration
    assert "ix_evidence_records_mission_id" in migration
    assert "ix_evidence_records_execution_task_id" in migration
    assert "ix_evidence_records_capability_id" in migration
    assert "ix_evidence_records_capability_adapter_id" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "tenant_evidence_isolation" in migration
    assert "def downgrade" in migration
