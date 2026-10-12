from __future__ import annotations

from backend.queue.adapters.redis_adapter import RedisQueueAdapter


class OwnerSafeRedisQueueAdapter(RedisQueueAdapter):
    """Compatibility name for the canonical owner-safe indexed Redis adapter."""
