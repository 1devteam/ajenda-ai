from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_billing_meter_dispatch_migration_is_current_head_and_durable() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0057_assessment_retry_dedup"]

    migration = Path("alembic/versions/0051_billing_meter_dispatches.py").read_text(encoding="utf-8")
    assert 'down_revision = "0050_runtime_queue_dispatches"' in migration
    assert '"billing_meter_dispatches"' in migration
    assert 'ForeignKey("tenants.id", ondelete="RESTRICT")' in migration
    assert "ck_billing_meter_dispatches_metric" in migration
    assert "ck_billing_meter_dispatches_quantity" in migration
    assert "ck_billing_meter_dispatches_status" in migration
    assert "ck_billing_meter_dispatches_attempt_count" in migration
    assert "ix_billing_meter_dispatches_due" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_id::text = current_setting('app.current_tenant_id', true)" in migration
    assert "CREATE POLICY admin_bypass" in migration
    assert 'op.drop_table("billing_meter_dispatches")' in migration
