from __future__ import annotations

from pathlib import Path


def test_compose_production_env_documents_webhook_secret_encryption_key() -> None:
    content = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")

    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY=" in content
    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV=" in content
    assert "Fernet.generate_key()" in content
    assert "CHANGE_ME_GENERATE_WITH_FERNET" in content


def test_k8s_secret_example_documents_webhook_secret_encryption_key() -> None:
    content = Path("deploy/k8s/secret.example.yaml").read_text(encoding="utf-8")

    assert "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY" in content
    assert "<REPLACE_FERNET_KEY>" in content
