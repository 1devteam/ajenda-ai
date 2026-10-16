from pathlib import Path


def test_secret_manifest_uses_placeholders_only() -> None:
    content = Path("deploy/k8s/secret.example.yaml").read_text(encoding="utf-8")
    assert "<REPLACE_POSTGRES_PASSWORD>" in content
    assert "postgresql+psycopg://ajenda_api:<REPLACE_API_PASSWORD>@postgres:5432/ajenda" in content
    assert "AJENDA_DATABASE_URL:" not in content


def test_ci_does_not_define_a_shared_fixed_database_password() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "AJENDA_DATABASE_URL:" not in workflow
    assert "POSTGRES_PASSWORD: ajenda_test" not in workflow
