from pathlib import Path


def test_initial_migration_contains_authoritative_tables() -> None:
    migration = Path("alembic/versions/0001_initial_runtime_schema.py").read_text(encoding="utf-8")
    for table_name in [
        "missions",
        "workforce_fleets",
        "user_workforce_agents",
        "execution_tasks",
        "execution_branches",
        "worker_leases",
        "governance_events",
        "audit_events",
        "lineage_records",
    ]:
        assert f'"{table_name}"' in migration


def test_initial_migration_contains_real_foreign_keys() -> None:
    migration = Path("alembic/versions/0001_initial_runtime_schema.py").read_text(encoding="utf-8")
    assert '["mission_id"], ["missions.id"]' in migration
    assert '["task_id"], ["execution_tasks.id"]' in migration
    assert '["worker_lease_id"], ["worker_leases.id"]' in migration


def test_audit_event_rls_migration_forces_tenant_isolation() -> None:
    migration = Path("alembic/versions/0064_force_audit_event_rls.py").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_audit_event_isolation" in migration
    assert "current_setting('app.current_tenant_id', true)" in migration
