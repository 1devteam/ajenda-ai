from __future__ import annotations

from backend.app.config import Settings
from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult
from backend.queue.local_adapter import LocalQueueAdapter
from backend.queue.adapters.redis_adapter import RedisQueueAdapter


def build_queue_adapter(settings: Settings) -> QueueAdapter:
    if settings.queue_adapter == "local":
        return LocalQueueAdapter()
    if settings.queue_adapter == "redis":
        if settings.queue_url is None:
            raise ValueError("AJENDA_QUEUE_URL is required for redis adapter")
        return RedisQueueAdapter(settings.queue_url)
    raise ValueError(f"Unsupported queue adapter: {settings.queue_adapter}")


__all__ = [
    "QueueAdapter",
    "QueueMessage",
    "QueueOperationResult",
    "LocalQueueAdapter",
    "RedisQueueAdapter",
    "build_queue_adapter",
]
