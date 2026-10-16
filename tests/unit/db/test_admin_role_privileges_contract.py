from pathlib import Path


def test_role_separation_migration_removes_legacy_admin_bypass_and_grants_runtime_dml() -> None:
    migration = Path("alembic/versions/0052_db_role_separation.py").read_text(encoding="utf-8")

    assert "DROP POLICY IF EXISTS admin_bypass" in migration
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ajenda_admin" in migration
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO" in migration
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ajenda_assurance" in migration
    assert "GRANT INSERT, UPDATE ON TABLE assurance_snapshots, assurance_metric_state TO ajenda_assurance" in migration


def test_pretenant_auth_records_are_not_granted_to_worker_or_assurance() -> None:
    migration = Path("alembic/versions/0053_restrict_auth_runtime.py").read_text(encoding="utf-8")

    assert '"customer_auth_sessions"' in migration
    assert '"oidc_login_intents"' in migration
    assert '"signup_attempt_log"' in migration
    assert '"tenant_members"' in migration
    assert "REVOKE ALL ON TABLE public.{table} FROM {role}" in migration


def test_bootstrap_hardens_existing_roles_and_removes_runtime_memberships() -> None:
    source = Path("deploy/sql/database_role_bootstrap.sql").read_text(encoding="utf-8")

    for role in ("ajenda_migrator", "ajenda_api", "ajenda_worker", "ajenda_assurance"):
        assert f"ALTER ROLE {role} LOGIN NOSUPERUSER" in source
    assert "NOBYPASSRLS" in source
    assert "REVOKE %I FROM %I" in source
