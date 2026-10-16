"""Ensure role provisioning does not expose credentials via CLI arguments."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_credentials_come_from_psql_environment() -> None:
    sql = (ROOT / "deploy/sql/database_role_bootstrap.sql").read_text(encoding="utf-8")
    script = (ROOT / "deploy/scripts/provision-database-roles.sh").read_text(encoding="utf-8")
    for role in ("api", "worker", "assurance", "migrator"):
        env_var = f"AJENDA_{role.upper()}_DATABASE_PASSWORD"
        assert f"\\getenv {role}_password {env_var}" in sql
        assert f"-v {role}_password=" not in script
    assert 'urlparse(os.environ["AJENDA_DATABASE_BOOTSTRAP_URL"])' in script
    assert 'psql "$AJENDA_DATABASE_BOOTSTRAP_URL"' not in script


def test_compose_bootstrap_does_not_include_password_in_psql_argv() -> None:
    for name in ("docker-compose.yml", "deploy/compose/docker-compose.prod.yml"):
        source = (ROOT / name).read_text(encoding="utf-8")
        bootstrap = source.split("\n  role-bootstrap:\n", 1)[1].split("\n  db:\n", 1)[0]
        assert "-f /bootstrap/database_role_bootstrap.sql" in bootstrap
        for role in ("api", "worker", "assurance", "migrator"):
            assert f"-v {role}_password=" not in bootstrap
