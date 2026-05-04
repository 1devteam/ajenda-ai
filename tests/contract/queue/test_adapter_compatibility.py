from backend.queue.adapters.redis_adapter import RedisQueueAdapter
from backend.queue.local_adapter import LocalQueueAdapter


def test_supported_queue_adapter_classes_are_explicit() -> None:
    assert RedisQueueAdapter is not None
    assert LocalQueueAdapter is not None
