from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TtlCache(Generic[T]):
    def __init__(self, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, _CacheEntry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if monotonic() >= entry.expires_at:
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: T) -> None:
        self._store[key] = _CacheEntry(value=value, expires_at=monotonic() + self._ttl_seconds)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)
