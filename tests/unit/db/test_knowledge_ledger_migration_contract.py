from pathlib import Path


def test_knowledge_ledger_migration_preserves_tenant_identity_and_rls_contract() -> None:
    migration = Path("alembic/versions/0037_add_durable_knowledge_ledger.py").read_text()

    assert 'down_revision = "0036_composition_thread"' in migration
    assert 'UniqueConstraint("tenant_id", "qualification_id"' in migration
    assert 'UniqueConstraint("tenant_id", "knowledge_id"' in migration
    assert '["qualification_record_id", "tenant_id"]' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('app.current_tenant_id', true)" in migration
    assert "DROP POLICY IF EXISTS tenant_isolation" in migration
