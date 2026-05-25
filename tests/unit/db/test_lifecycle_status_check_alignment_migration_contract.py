from __future__ import annotations

from pathlib import Path


def test_lifecycle_status_check_alignment_migration_expands_allowed_values() -> None:
    migration = Path("alembic/versions/0020_expand_evidence_outcome_lifecycle_checks.py").read_text(encoding="utf-8")

    assert "ck_evidence_records_collection_status" in migration
    for status in (
        "draft",
        "collected",
        "verified",
        "rejected",
        "superseded",
        "retention_hold",
        "archived",
        "purged",
    ):
        assert status in migration

    assert "ck_outcome_reviews_review_status" in migration
    for status in ("draft", "in_review", "completed", "superseded", "escalated", "archived"):
        assert status in migration

    assert "ck_outcome_reviews_human_approval_status" in migration
    for status in ("not_required", "pending", "approved", "rejected", "escalated"):
        assert status in migration

    assert "op.drop_constraint" in migration
    assert "op.create_check_constraint" in migration


def test_lifecycle_status_check_alignment_migration_downgrade_restores_prior_sets() -> None:
    migration = Path("alembic/versions/0020_expand_evidence_outcome_lifecycle_checks.py").read_text(encoding="utf-8")

    assert "EVIDENCE_COLLECTION_STATUS_V1" in migration
    assert "OUTCOME_REVIEW_STATUS_V1" in migration
    assert "HUMAN_APPROVAL_STATUS_V1" in migration
    assert "def downgrade" in migration
