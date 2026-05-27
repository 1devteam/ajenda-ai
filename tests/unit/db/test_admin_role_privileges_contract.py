from pathlib import Path


def test_row_level_security_migration_grants_table_privileges_to_ajenda_admin() -> None:
    migration = Path("alembic/versions/0003_row_level_security.py").read_text(encoding="utf-8")

    assert "GRANT USAGE ON SCHEMA public TO ajenda_admin" in migration
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE" in migration
    assert "pg_get_serial_sequence(table_name, 'id')" in migration
    assert "GRANT USAGE, SELECT ON SEQUENCE %s TO ajenda_admin" in migration
