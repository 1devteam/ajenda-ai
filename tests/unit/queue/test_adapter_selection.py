import pytest

from backend.app.config import Settings
from backend.queue import build_queue_adapter
from backend.queue.adapters.redis_adapter import RedisQueueAdapter
from backend.queue.local_adapter import LocalQueueAdapter


def test_local_adapter_selected_explicitly() -> None:
    settings = Settings.model_construct(
        database_url="sqlite://",
        env="development",
        queue_adapter="local",
        queue_url=None,
        port=8000,
        log_json=False,
    )
    assert isinstance(build_queue_adapter(settings), LocalQueueAdapter)


def test_redis_adapter_selected_explicitly() -> None:
    settings = Settings.model_construct(
        database_url="sqlite://",
        env="development",
        queue_adapter="redis",
        queue_url="redis://redis:6379/0",
        port=8000,
        log_json=False,
    )
    assert isinstance(build_queue_adapter(settings), RedisQueueAdapter)


def test_production_local_adapter_is_rejected() -> None:
    settings = Settings.model_construct(
        database_url="sqlite://",
        env="production",
        queue_adapter="local",
        queue_url=None,
        port=8000,
        log_json=True,
    )
    with pytest.raises(ValueError):
        settings.validate_runtime_contract()
