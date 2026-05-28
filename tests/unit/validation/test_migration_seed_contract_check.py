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


def test_migration_seed_contract_check_flags_multiline_insert_value_far_from_column_name() -> None:
    migration = """
    INSERT INTO capabilities (
        id,
        tenant_id,
        name,
        version,
        description,
        supported_task_types,
        input_schema_hints,
        output_schema_hints,
        required_permissions,
        required_tools,
        risk_level,
        approval_requirements,
        evidence_expectations,
        execution_constraints,
        enabled,
        schema_version,
        created_at,
        updated_at
    )
    VALUES (
        gen_random_uuid(), NULL, 'gtm_outbound_email', '1.0.0',
        'Global GTM outbound email planning capability.',
        '["outbound_campaign"]'::jsonb,
        '{"required": ["campaign_brief"]}'::jsonb,
        '{"produces": ["outbound_plan"]}'::jsonb,
        '[]'::jsonb,
        '["email"]'::jsonb,
        'high',
        '{"human_approval": true}'::jsonb,
        '{"required_events": ["approval_decision", "send_outcome"]}'::jsonb,
        '{"policy_gated": true, "feature_flag": "gtm_enabled"}'::jsonb,
        true, 1, now(), now()
    )
    ON CONFLICT (name, version)
    WHERE tenant_id IS NULL
    DO NOTHING
    """

    issues = _check_migration(Path("alembic/versions/9999_demo.py"), migration)

    assert len(issues) == 1
    assert issues[0].field_name == "capabilities.evidence_expectations"
    assert issues[0].expected_kind == "array"
    assert issues[0].observed_kind == "object"


def test_migration_seed_contract_check_flags_insert_select_object_literals() -> None:
    migration = """
    INSERT INTO capability_adapters (
        id,
        evidence_expectations,
        timeout_retry_hints
    )
    SELECT
        gen_random_uuid(),
        '{"required_events": ["approval_decision", "delivery_outcome"]}'::jsonb,
        '{"timeout_seconds": 120}'::jsonb
    FROM capabilities
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
