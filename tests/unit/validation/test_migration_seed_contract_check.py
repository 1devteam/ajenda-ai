from pathlib import Path

from scripts.validation.migration_seed_contract_check import _check_migration


def test_migration_seed_contract_check_accepts_array_literals_for_evidence_expectations() -> None:
    migration = """
    INSERT INTO capabilities (name, evidence_expectations)
    VALUES ('demo', '["approval_decision", "send_outcome"]'::jsonb)
    """

    issues = _check_migration(Path("alembic/versions/9999_demo.py"), migration)

    assert issues == []


def test_migration_seed_contract_check_flags_object_literals_for_evidence_expectations() -> None:
    migration = """
    INSERT INTO capability_adapters (name, evidence_expectations, timeout_retry_hints)
    VALUES (
        'demo_adapter',
        '{"required_events": ["approval_decision"]}'::jsonb,
        '{}'::jsonb
    )
    """

    issues = _check_migration(Path("alembic/versions/9999_demo.py"), migration)

    assert len(issues) == 1
    assert issues[0].field_name == "capability_adapters.evidence_expectations"
    assert issues[0].expected_kind == "array"
    assert issues[0].observed_kind == "object"


def test_migration_seed_contract_check_ignores_untracked_fields() -> None:
    migration = """
    INSERT INTO capabilities (name, execution_constraints)
    VALUES ('demo', '{"policy_gated": true}'::jsonb)
    """

    issues = _check_migration(Path("alembic/versions/9999_demo.py"), migration)

    assert issues == []
