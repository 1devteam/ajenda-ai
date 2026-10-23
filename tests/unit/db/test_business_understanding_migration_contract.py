from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_business_understanding_migration_is_current_head_and_short_revision_id() -> None:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()

    assert heads == ["0057_assessment_retry_dedup"]
    assert len(heads[0]) <= 32


def test_business_understanding_migration_persists_append_only_tenant_contracts() -> None:
    foundation = Path("alembic/versions/0055_business_understanding.py").read_text(encoding="utf-8")
    assessment = Path("alembic/versions/0056_business_need_assessments.py").read_text(encoding="utf-8")

    assert "business_observations" in foundation
    assert "business_need_revisions" in foundation
    assert "uq_business_need_revisions_tenant_need_revision" in foundation
    assert "previous_revision_id" in foundation
    assert 'sa.Column("producer", sa.String(length=160), nullable=False)' in foundation
    assert "observation_references" in foundation
    assert "resolution_observation_references" in foundation
    assert "business_need_assessments" in assessment
    assert "assessment_fingerprint" in assessment
    assert "fk_business_need_assessments_need_revision_tenant" in assessment
    assert "ENABLE ROW LEVEL SECURITY" in foundation and "ENABLE ROW LEVEL SECURITY" in assessment
    assert "FORCE ROW LEVEL SECURITY" in foundation and "FORCE ROW LEVEL SECURITY" in assessment
    assert (
        "tenant_business_understanding_isolation" in foundation
        and "tenant_business_understanding_isolation" in assessment
    )
    assert "def downgrade" in foundation and "def downgrade" in assessment
