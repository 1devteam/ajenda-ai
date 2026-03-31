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
    assert adapter.ping() is True
