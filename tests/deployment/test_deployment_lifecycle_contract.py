"""Behavioral drift guards for the explicit database provisioning lifecycle."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "deploy/compose/docker-compose.prod.yml",
)
PROOF = ROOT / "deploy/scripts/live-runtime-proof.sh"
README = ROOT / "deploy/compose/README.database-lifecycle.md"


def _service_block(source: str, name: str) -> str:
    # Anchor at the start of the line. A substring split also matches
    # nested keys such as depends_on.api (six-space indentation).
    start = re.search(rf"(?m)^  {re.escape(name)}:[ \\t]*$", source)
    assert start is not None, f"Missing service {name}"
    remainder = source[start.end() :]
    next_service = re.search(r"(?m)^  [a-z][a-z0-9-]*:[ \\t]*$", remainder)
    return remainder[: next_service.start()] if next_service else remainder


def test_bootstrap_is_opt_in_for_all_compose_variants() -> None:
    for path in COMPOSE_FILES:
        compose = path.read_text(encoding="utf-8")
        bootstrap = _service_block(compose, "role-bootstrap")
        migration = _service_block(compose, "migrate")
        assert 'profiles: ["bootstrap"]' in bootstrap, str(path)
        assert "role-bootstrap:" not in migration, str(path)
        assert "db:" in migration, str(path)
        assert "condition: service_healthy" in migration, str(path)


def test_runtime_services_remain_gated_by_completed_migration() -> None:
    for path in COMPOSE_FILES:
        compose = path.read_text(encoding="utf-8")
        for service in ("api", "worker", "assurance"):
            block = _service_block(compose, service)
            assert "migrate:" in block, (str(path), service)
            assert "condition: service_completed_successfully" in block, (str(path), service)


def test_database_restarts_without_reprovisioning_persistent_storage() -> None:
    """The database survives daemon restarts; bootstrap remains explicit."""
    for path in COMPOSE_FILES:
        compose = path.read_text(encoding="utf-8")
        database = _service_block(compose, "db")

        assert "restart: unless-stopped" in database, str(path)
        assert "postgres_data:/var/lib/postgresql/data" in database, str(path)


def test_database_healthcheck_does_not_require_a_bootstrapped_role() -> None:
    """Fresh volumes must become healthy before the opt-in role bootstrap."""
    for path in COMPOSE_FILES:
        database = _service_block(path.read_text(encoding="utf-8"), "db")

        assert "pg_isready -d ajenda" in database, str(path)
        assert "pg_isready -U" not in database, str(path)


def test_runtime_proof_defaults_to_observation_without_teardown() -> None:
    script = PROOF.read_text(encoding="utf-8")
    assert "compose down" not in script
    assert "AJENDA_PROOF_START_SERVICES:-0" in script
    assert "AJENDA_PROOF_BOOTSTRAP_ROLES:-0" in script
    assert "AJENDA_PROOF_REBUILD:-0" in script
    assert "requires AJENDA_PROOF_START_SERVICES=1" in script
    assert 'compose up -d "${proof_build_args[@]}"' in script
    assert "compose --profile bootstrap run --rm role-bootstrap" in script


def test_operator_documentation_distinguishes_bootstrap_and_normal_start() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--profile bootstrap run --rm role-bootstrap" in text
    assert "Existing database / routine startup" in text
    assert "AJENDA_PROOF_START_SERVICES=1" in text
    assert "docker compose down -v" in text
