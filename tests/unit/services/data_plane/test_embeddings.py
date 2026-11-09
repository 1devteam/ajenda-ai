from __future__ import annotations

import math

import pytest

from backend.app.config import Settings
from backend.services.data_plane.embeddings import (
    DeterministicEmbeddingProvider,
    OpenAiCompatibleEmbeddingProvider,
    cosine_similarity,
    deterministic_embedding,
)


def test_deterministic_embedding_is_stable_and_normalized() -> None:
    first = deterministic_embedding("roofing contractors austin")
    second = deterministic_embedding("roofing contractors austin")

    assert first == second
    assert len(first) == 32
    norm = math.sqrt(sum(value * value for value in first))
    assert norm == pytest.approx(1.0)


def test_cosine_similarity_prefers_related_text() -> None:
    left = deterministic_embedding("roofing contractors austin")
    related = deterministic_embedding("austin roofing contractor leads")
    unrelated = deterministic_embedding("quantum chromatography synthesis")

    assert cosine_similarity(left, related) > cosine_similarity(left, unrelated)


def test_deterministic_provider_is_explicitly_labelled_as_lexical_fallback() -> None:
    provider = DeterministicEmbeddingProvider()

    assert provider.provider_id == "deterministic_hash.v1"
    assert provider.embed("roofing contractors austin") == deterministic_embedding("roofing contractors austin")


def test_openai_embedding_provider_rejects_missing_key() -> None:
    provider = OpenAiCompatibleEmbeddingProvider(settings=Settings(embedding_api_key=None))

    with pytest.raises(ValueError, match="embedding API key is not configured"):
        provider.embed("semantic search")
