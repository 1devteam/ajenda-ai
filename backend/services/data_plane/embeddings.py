from __future__ import annotations

import hashlib
import math
import re

_EMBEDDING_DIM = 32
_TOKEN_RE = re.compile(r"[a-z0-9]+")


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

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
