import os

import pytest

from backend.app.config import Settings
from backend.queue import build_queue_adapter
from backend.queue.adapters.redis_adapter import RedisQueueAdapter


def test_redis_runtime_boot_selects_redis_adapter() -> None:
    settings = Settings.model_construct(
        database_url="sqlite://",
        env="development",
        queue_adapter="redis",
        queue_url="redis://redis:6379/0",
        port=8000,
        log_json=False,
    )

    adapter = build_queue_adapter(settings)

    assert isinstance(adapter, RedisQueueAdapter)


def test_redis_runtime_ping_requires_live_redis() -> None:
    redis_url = os.getenv("AJENDA_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("AJENDA_TEST_REDIS_URL is required for live Redis ping validation")

    settings = Settings.model_construct(
        database_url="sqlite://",
        env="development",
        queue_adapter="redis",
        queue_url=redis_url,
        port=8000,
        log_json=False,
    )

    adapter = build_queue_adapter(settings)

    assert isinstance(adapter, RedisQueueAdapter)
    assert adapter.ping() is True
