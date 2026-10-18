"""Behavioral drift guards for the explicit database provisioning lifecycle."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "deploy/compose/docker-compose.prod.yml",
)
PROOF = ROOT / "deploy/scripts/live-runtime-proof.sh"
README = ROOT / "deploy/compose/README.database-lifecycle.md"


def _service_block(source: str, name: str) -> str:
    prefix = f"  {name}:\n"
    assert prefix in source, f"Missing service {name}"
    remainder = source.split(prefix, 1)[1]
    # Only a top-level service key ends a block. Nested mapping keys
    # (depends_on, db, migrate) are indented by four or more spaces.
    next_service = re.search(r"(?m)^  [a-z][a-z0-9-]*:\\s*$", remainder)
    return remainder[:next_service.start()] if next_service else remainder


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


def test_runtime_proof_defaults_to_observation_without_teardown() -> None:
    script = PROOF.read_text(encoding="utf-8")
    assert "compose down" not in script
    assert 'AJENDA_PROOF_START_SERVICES:-0' in script
    assert 'AJENDA_PROOF_REBUILD:-0' in script
    assert 'requires AJENDA_PROOF_START_SERVICES=1' in script
    assert 'compose up -d "${proof_build_args[@]}"' in script


def test_operator_documentation_distinguishes_bootstrap_and_normal_start() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--profile bootstrap run --rm role-bootstrap" in text
    assert "Existing database / routine startup" in text
    assert "AJENDA_PROOF_START_SERVICES=1" in text
    assert "docker compose down -v" in text
