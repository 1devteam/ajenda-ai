from pathlib import Path


def test_queue_adapter_selected_by_env_contract() -> None:
    content = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")
    assert "AJENDA_QUEUE_ADAPTER=redis" in content
