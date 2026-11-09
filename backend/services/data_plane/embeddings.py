from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol
from urllib.parse import urlparse

from backend.app.config import Settings, get_settings
from backend.services.network_egress import NetworkEgressAuthority, get_default_network_egress_authority

_EMBEDDING_DIM = 32
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    """A synchronous embedding provider with explicit model provenance."""

    provider_id: str

    def embed(self, text: str) -> list[float]: ...


class DeterministicEmbeddingProvider:
    """Compatibility fallback; lexical hashing is not semantic retrieval."""

    provider_id = "deterministic_hash.v1"

    def embed(self, text: str) -> list[float]:
        return deterministic_embedding(text)


class OpenAiCompatibleEmbeddingProvider:
    """Governed OpenAI-compatible embedding client for semantic retrieval."""

    def __init__(self, *, settings: Settings, network_egress_authority: NetworkEgressAuthority | None = None) -> None:
        self._settings = settings
        self._network_egress_authority = network_egress_authority or get_default_network_egress_authority()
        self.provider_id = f"openai_compatible:{settings.embedding_model}"

    def embed(self, text: str) -> list[float]:
        api_key = str(self._settings.embedding_api_key or "").strip()
        if not api_key:
            raise ValueError("embedding API key is not configured")
        normalized = text.strip()
        if not normalized:
            return []
        base_url = str(self._settings.embedding_base_url).rstrip("/")
        host = urlparse(base_url).hostname
        if not host:
            raise ValueError("embedding base URL must include a hostname")
        _, response = self._network_egress_authority.request(
            method="POST",
            url=f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_body={"model": self._settings.embedding_model, "input": normalized},
            timeout_seconds=float(self._settings.embedding_timeout_seconds),
            allowed_hosts=[host],
            action_name="embedding.openai_compatible",
            response_text_limit=1_048_576,
        )
        if response.status_code >= 400:
            raise ValueError(f"embedding request failed with status {response.status_code}")
        try:
            payload = json.loads(response.body_text)
            data = payload.get("data")
            vector = data[0].get("embedding") if isinstance(data, list) and data and isinstance(data[0], dict) else None
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("embedding response is invalid") from exc
        if not isinstance(vector, list) or not vector or not all(isinstance(item, (int, float)) for item in vector):
            raise ValueError("embedding response has no numeric vector")
        return _normalize_vector([float(item) for item in vector])


def get_embedding_provider(*, settings: Settings | None = None) -> EmbeddingProvider:
    resolved = settings or get_settings()
    if resolved.embedding_ready:
        return OpenAiCompatibleEmbeddingProvider(settings=resolved)
    return DeterministicEmbeddingProvider()


def _normalize_vector(vector: list[float]) -> list[float]:
    if not vector or not all(math.isfinite(item) for item in vector):
        raise ValueError("embedding vector must contain finite values")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        raise ValueError("embedding vector must have non-zero magnitude")
    return [value / norm for value in vector]


def deterministic_embedding(text: str, *, dimensions: int = _EMBEDDING_DIM) -> list[float]:
    """Build a deterministic local embedding without external model calls."""
    vector = [0.0] * dimensions
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(dimensions):
            byte = digest[index % len(digest)]
            vector[index] += ((byte / 255.0) * 2.0) - 1.0

    return _normalize_vector(vector)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
