"""Shared contracts for governed internet access helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.services.internet.modes import InternetAccessMode


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    snippet: str
    url: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class SearchBundle:
    provider: str
    real: bool
    results: tuple[SearchHit, ...] = ()
    status_code: int | None = None
    error: str | None = None
    access_mode: InternetAccessMode = InternetAccessMode.PUBLIC_SEARCH

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "real": self.real,
            "results": [item.as_dict() for item in self.results],
            "result_count": len(self.results),
            "status_code": self.status_code,
            "error": self.error,
            "access_mode": self.access_mode.value,
        }


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    url: str
    real: bool
    status_code: int | None = None
    title: str | None = None
    text_preview: str | None = None
    body_preview: str | None = None
    body_truncated: bool = False
    content_type: str | None = None
    error: str | None = None
    access_mode: InternetAccessMode = InternetAccessMode.PAGE_READ
    extraction: dict[str, Any] = field(default_factory=dict)
    # Future browser_session may attach navigation trail / screenshot refs here.
    browser_ready: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "real": self.real,
            "status_code": self.status_code,
            "title": self.title,
            "text_preview": self.text_preview,
            "body_preview": self.body_preview,
            "body_truncated": self.body_truncated,
            "content_type": self.content_type,
            "error": self.error,
            "access_mode": self.access_mode.value,
            "extraction": dict(self.extraction),
            "browser_ready": self.browser_ready,
        }
