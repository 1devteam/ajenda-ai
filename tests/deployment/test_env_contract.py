from pathlib import Path


def test_env_contract_contains_queue_and_database() -> None:
    content = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")
    assert "AJENDA_DATABASE_URL" in content
    assert "AJENDA_QUEUE_ADAPTER" in content
    assert "AJENDA_QUEUE_URL" in content
