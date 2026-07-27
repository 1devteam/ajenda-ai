from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_outcome_review_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0035_composition_proposals"]
    assert len(heads[0]) <= 32


def test_outcome_review_migration_contains_tenant_indexes_jsonb_and_rls_policies() -> None:
    migration = Path("alembic/versions/0014_outcome_reviews.py").read_text(encoding="utf-8")

    assert "outcome_reviews" in migration
    assert "ix_outcome_reviews_tenant_id" in migration
    assert "ix_outcome_reviews_mission_id" in migration
    assert "postgresql.JSONB" in migration
    assert "evidence_references" in migration
    assert "structured_findings" in migration
    assert "unresolved_gaps" in migration
    assert "recommended_next_actions" in migration
    assert "trust_signal" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "tenant_outcome_review_isolation" in migration
    assert "def downgrade" in migration
