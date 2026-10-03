from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_knowledge_change_proposal_migration_is_current_head_and_rls_scoped() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0046_knowledge_change_proposals"]
    migration = Path("alembic/versions/0046_knowledge_change_proposals.py").read_text(encoding="utf-8")
    assert "knowledge_change_proposals" in migration
    assert "tenant_knowledge_change_proposal_isolation" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "rolled_back" in migration
