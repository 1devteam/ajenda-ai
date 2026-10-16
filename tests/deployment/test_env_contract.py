from pathlib import Path


def test_env_contract_contains_queue_and_database() -> None:
    content = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")
    for name in (
        "AJENDA_DATABASE_BOOTSTRAP_URL",
        "AJENDA_API_DATABASE_PASSWORD",
        "AJENDA_WORKER_DATABASE_PASSWORD",
        "AJENDA_ASSURANCE_DATABASE_PASSWORD",
        "AJENDA_MIGRATOR_DATABASE_PASSWORD",
    ):
        assert name in content
    assert "AJENDA_QUEUE_ADAPTER" in content
    assert "AJENDA_QUEUE_URL" in content
