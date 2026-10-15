from pathlib import Path


def test_secret_manifest_uses_placeholders_only() -> None:
    content = Path("deploy/k8s/secret.example.yaml").read_text(encoding="utf-8")
    assert "<REPLACE_POSTGRES_PASSWORD>" in content
    assert "postgresql+psycopg://ajenda_api:<REPLACE_API_PASSWORD>@postgres:5432/ajenda" in content
    assert "AJENDA_DATABASE_URL:" not in content
