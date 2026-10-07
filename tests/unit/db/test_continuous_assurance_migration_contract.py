from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_continuous_assurance_migration_is_current_head_and_tenant_scoped() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0049_continuous_assurance"]

    migration = Path("alembic/versions/0049_continuous_assurance.py").read_text(encoding="utf-8")
    assert "assurance_snapshots" in migration
    assert "assurance_metric_state" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_assurance_snapshot_isolation" in migration
    assert "authority_class = 'read_model' AND grants_execution_authority = false" in migration
    assert "DROP POLICY IF EXISTS tenant_assurance_snapshot_isolation" in migration
