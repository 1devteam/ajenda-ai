from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_runtime_queue_dispatch_migration_is_current_head_and_durable() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0053_restrict_auth_runtime"]

    migration = Path("alembic/versions/0050_runtime_queue_dispatches.py").read_text(encoding="utf-8")
    assert 'down_revision = "0049_continuous_assurance"' in migration
    assert '"runtime_queue_dispatches"' in migration
    assert 'ForeignKey("execution_tasks.id", ondelete="RESTRICT")' in migration
    assert 'UniqueConstraint("task_id", name="uq_runtime_queue_dispatches_task")' in migration
    assert "ck_runtime_queue_dispatches_status" in migration
    assert "ck_runtime_queue_dispatches_attempt_count" in migration
    assert "ix_runtime_queue_dispatches_due" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_runtime_queue_dispatch_isolation" in migration
    assert "current_setting('app.current_tenant_id', true)" in migration
    assert "CREATE POLICY admin_bypass" in migration
    assert 'op.drop_table("runtime_queue_dispatches")' in migration
