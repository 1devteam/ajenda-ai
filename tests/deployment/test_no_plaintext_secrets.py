from pathlib import Path


def test_secret_manifest_uses_placeholders_only() -> None:
    content = Path("deploy/k8s/secret.example.yaml").read_text(encoding="utf-8")
    assert "<REPLACE_POSTGRES_PASSWORD>" in content
    assert "postgresql+psycopg://ajenda:<REPLACE_POSTGRES_PASSWORD>@postgres:5432/ajenda" in content
