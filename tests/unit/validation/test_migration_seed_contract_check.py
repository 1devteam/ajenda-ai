from __future__ import annotations

from pathlib import Path

from scripts.validation import migration_seed_contract_check as seed_check


def _write_migration(path: Path, body: str) -> Path:
    migration = path / "0001_seed_contract.py"
    migration.write_text(body, encoding="utf-8")
    return migration


def test_current_migrations_satisfy_seed_contracts() -> None:
    assert seed_check.check_migrations() == []


def test_capability_evidence_expectations_must_be_array(tmp_path: Path) -> None:
    migration = _write_migration(
        tmp_path,
        """
        INSERT INTO capabilities (
            name, version, supported_task_types, input_schema_hints,
            output_schema_hints, required_permissions, required_tools,
            approval_requirements, evidence_expectations, execution_constraints
        )
        VALUES (
            'bad_capability', '1.0.0', '["task"]'::jsonb, '{}'::jsonb,
            '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '{}'::jsonb, '{"required_events": ["x"]}'::jsonb, '{}'::jsonb
        )
        """,
    )

    issues = seed_check.check_migration_file(migration)

    assert len(issues) == 1
    assert issues[0].table == "capabilities"
    assert issues[0].field == "evidence_expectations"
    assert "expected array JSONB seed literal, found object" in issues[0].message


def test_capability_adapter_select_seed_contracts_are_validated(tmp_path: Path) -> None:
    migration = _write_migration(
        tmp_path,
        """
        INSERT INTO capability_adapters (
            name, version, capability_id, supported_task_types, input_contract,
            output_contract, required_permissions, required_tools, approval_requirements,
            evidence_expectations, timeout_retry_hints, idempotency_expectations
        )
        SELECT
            'adapter', '1.0.0', c.id, '["task"]'::jsonb, '{}'::jsonb,
            '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb,
            '["event"]'::jsonb, '{}'::jsonb, '{}'::jsonb
        FROM capabilities c
        """,
    )

    assert seed_check.check_migration_file(migration) == []


def test_object_contract_fields_must_not_be_seeded_as_arrays(tmp_path: Path) -> None:
    migration = _write_migration(
        tmp_path,
        """
        INSERT INTO capability_adapters (
            name, version, supported_task_types, input_contract, output_contract,
            required_permissions, required_tools, approval_requirements, evidence_expectations,
            timeout_retry_hints, idempotency_expectations
        )
        VALUES (
            'adapter', '1.0.0', '["task"]'::jsonb, '[]'::jsonb, '{}'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '["event"]'::jsonb,
            '{}'::jsonb, '{}'::jsonb
        )
        """,
    )

    issues = seed_check.check_migration_file(migration)

    assert len(issues) == 1
    assert issues[0].table == "capability_adapters"
    assert issues[0].field == "input_contract"
    assert "expected object JSONB seed literal, found array" in issues[0].message


def test_nonliteral_contract_seed_requires_explicit_review(tmp_path: Path) -> None:
    migration = _write_migration(
        tmp_path,
        """
        INSERT INTO capabilities (
            name, version, supported_task_types, input_schema_hints,
            output_schema_hints, required_permissions, required_tools,
            approval_requirements, evidence_expectations, execution_constraints
        )
        VALUES (
            'dynamic_capability', '1.0.0', jsonb_build_array('task'), '{}'::jsonb,
            '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '{}'::jsonb, '["event"]'::jsonb, '{}'::jsonb
        )
        """,
    )

    issues = seed_check.check_migration_file(migration)

    assert len(issues) == 1
    assert issues[0].field == "supported_task_types"
    assert "expected array JSONB seed literal" in issues[0].message
