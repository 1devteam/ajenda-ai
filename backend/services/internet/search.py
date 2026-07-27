"""Public web search providers — pluggable, chainable.

Priority (``AJENDA_PUBLIC_SEARCH_PROVIDER=auto``):
1. Brave Search API when ``AJENDA_BRAVE_SEARCH_API_KEY`` is set (egress)
2. SerpAPI when ``AJENDA_SERPAPI_API_KEY`` is set (egress)
3. ``duckduckgo-search`` / ddgs package (free; package-owned HTTP)
4. DuckDuckGo Instant Answer via NetworkEgressAuthority (fallback)

Brave/SerpAPI always use NetworkEgressAuthority. The ddgs package uses its own
HTTP client — discovery-only, no user-controlled URL navigation.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from backend.services.internet.contracts import SearchBundle, SearchHit
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import get_default_network_egress_authority

DDG_INSTANT_ANSWER_HOST = "api.duckduckgo.com"
BRAVE_SEARCH_HOST = "api.search.brave.com"
SERPAPI_HOST = "serpapi.com"
DEFAULT_SEARCH_PROVIDER = "duckduckgo_instant_answer"


class PublicSearchProvider(Protocol):
    """Extension point for alternate public search backends."""

    name: str

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle: ...


def _append_ddg_topic_result(
    results: list[SearchHit],
    *,
    item: dict[str, Any],
    limit: int,
    source: str,
) -> None:
    if len(results) >= limit:
        return
    text = item.get("Text")
    first_url = item.get("FirstURL")
    if not isinstance(text, str) or not text.strip():
        return
    title = text.strip().split(" - ", 1)[0][:160]
    results.append(
        SearchHit(
            title=title,
            snippet=text.strip()[:800],
            url=first_url if isinstance(first_url, str) else None,
            source=source,
        )
    )


def _collect_ddg_topics(
    items: object,
    *,
    results: list[SearchHit],
    limit: int,
    source: str,
) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if len(results) >= limit:
            break
        if not isinstance(item, dict):
            continue
        nested = item.get("Topics")
        if isinstance(nested, list):
            _collect_ddg_topics(nested, results=results, limit=limit, source=source)
            continue
        _append_ddg_topic_result(results, item=item, limit=limit, source=source)


class DuckDuckGoInstantAnswerProvider:
    name = DEFAULT_SEARCH_PROVIDER

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
        encoded_query = quote(query.strip())
        search_url = f"https://{DDG_INSTANT_ANSWER_HOST}/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
        try:
            _dest, response = get_default_network_egress_authority().request(
                method="GET",
                url=search_url,
                headers={"User-Agent": "AjendaInternet/1.0 (+public_search)"},
                allowed_hosts=[DDG_INSTANT_ANSWER_HOST],
                action_name="web.search",
                timeout_seconds=min(timeout_seconds, 15.0),
                response_text_limit=131_072,
            )
            if response.status_code >= 400:
                return SearchBundle(
                    provider=self.name,
                    real=False,
                    error=f"HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            if response.body_truncated:
                return SearchBundle(
                    provider=self.name,
                    real=False,
                    error="response truncated before JSON parse",
                    status_code=response.status_code,
                )
            payload = json.loads(response.body_text or "{}")
            if not isinstance(payload, dict):
                return SearchBundle(
                    provider=self.name,
                    real=False,
                    error="non-object JSON response",
                    status_code=response.status_code,
                )
            results: list[SearchHit] = []
            abstract = payload.get("AbstractText")
            abstract_url = payload.get("AbstractURL")
            if isinstance(abstract, str) and abstract.strip():
                heading = payload.get("Heading")
                results.append(
                    SearchHit(
                        title=str(heading)[:160] if isinstance(heading, str) and heading else query[:160],
                        snippet=abstract.strip()[:800],
                        url=abstract_url if isinstance(abstract_url, str) else None,
                        source=str(payload.get("AbstractSource") or "duckduckgo_abstract"),
                    )
                )
            _collect_ddg_topics(
                payload.get("Results"),
                results=results,
                limit=limit,
                source="duckduckgo_results",
            )
            _collect_ddg_topics(
                payload.get("RelatedTopics"),
                results=results,
                limit=limit,
                source="duckduckgo_related",
            )
            trimmed = tuple(results[:limit])
            return SearchBundle(
                provider=self.name,
                real=True,
                results=trimmed,
                status_code=response.status_code,
            )
        except Exception as exc:
            return SearchBundle(provider=self.name, real=False, error=str(exc))


class DuckDuckGoSearchPackageProvider:
    """Free discovery via duckduckgo-search / ddgs (package-owned HTTP)."""

    name = "ddgs"

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
        try:
            import importlib

            try:
                ddgs_mod = importlib.import_module("duckduckgo_search")
            except ImportError:  # pragma: no cover
                ddgs_mod = importlib.import_module("ddgs")
            ddgs_cls = getattr(ddgs_mod, "DDGS", None)
            if ddgs_cls is None:
                return SearchBundle(provider=self.name, real=False, error="ddgs package missing DDGS class")
        except ImportError as exc:
            return SearchBundle(provider=self.name, real=False, error=f"ddgs package unavailable: {exc}")

        try:
            hits: list[SearchHit] = []
            # DDGS context manager closes internal clients.
            with ddgs_cls() as client:
                raw_items = list(client.text(query.strip(), max_results=max(1, min(limit, 20))))
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("href") or "result").strip()[:160]
                snippet = str(item.get("body") or item.get("snippet") or "").strip()[:800]
                url = item.get("href") or item.get("link") or item.get("url")
                hits.append(
                    SearchHit(
                        title=title or "result",
                        snippet=snippet,
                        url=str(url)[:2048] if isinstance(url, str) and url.strip() else None,
                        source="ddgs",
                    )
                )
                if len(hits) >= limit:
                    break
            return SearchBundle(
                provider=self.name,
                real=True,
                results=tuple(hits),
            )
        except Exception as exc:
            return SearchBundle(provider=self.name, real=False, error=str(exc))


class BraveSearchProvider:
    name = "brave"

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key.strip()

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
        if not self._api_key:
            return SearchBundle(provider=self.name, real=False, error="AJENDA_BRAVE_SEARCH_API_KEY is not set")
        params = urlencode({"q": query.strip(), "count": str(max(1, min(limit, 20)))})
        search_url = f"https://{BRAVE_SEARCH_HOST}/res/v1/web/search?{params}"
        try:
            _dest, response = get_default_network_egress_authority().request(
                method="GET",
                url=search_url,
                headers={
                    "User-Agent": "AjendaInternet/1.0 (+public_search/brave)",
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
                allowed_hosts=[BRAVE_SEARCH_HOST],
                action_name="web.search",
                timeout_seconds=min(timeout_seconds, 15.0),
                response_text_limit=131_072,
            )
            if response.status_code >= 400:
                return SearchBundle(
                    provider=self.name,
                    real=False,
                    error=f"HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            payload = json.loads(response.body_text or "{}")
            web = payload.get("web") if isinstance(payload, dict) else None
            raw_results = web.get("results") if isinstance(web, dict) else None
            hits: list[SearchHit] = []
            if isinstance(raw_results, list):
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or "result").strip()[:160]
                    snippet = str(item.get("description") or "").strip()[:800]
                    url = item.get("url")
                    hits.append(
                        SearchHit(
                            title=title,
                            snippet=snippet,
                            url=str(url)[:2048] if isinstance(url, str) else None,
                            source="brave",
                        )
                    )
                    if len(hits) >= limit:
                        break
            return SearchBundle(
                provider=self.name,
                real=True,
                results=tuple(hits),
                status_code=response.status_code,
            )
        except Exception as exc:
            return SearchBundle(provider=self.name, real=False, error=str(exc))


class SerpApiSearchProvider:
    name = "serpapi"

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key.strip()

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
        if not self._api_key:
            return SearchBundle(provider=self.name, real=False, error="AJENDA_SERPAPI_API_KEY is not set")
        params = urlencode(
            {
                "engine": "google",
                "q": query.strip(),
                "num": str(max(1, min(limit, 10))),
                "api_key": self._api_key,
            }
        )
        search_url = f"https://{SERPAPI_HOST}/search.json?{params}"
        try:
            _dest, response = get_default_network_egress_authority().request(
                method="GET",
                url=search_url,
                headers={"User-Agent": "AjendaInternet/1.0 (+public_search/serpapi)", "Accept": "application/json"},
                allowed_hosts=[SERPAPI_HOST],
                action_name="web.search",
                timeout_seconds=min(timeout_seconds, 15.0),
                response_text_limit=131_072,
            )
            if response.status_code >= 400:
                return SearchBundle(
                    provider=self.name,
                    real=False,
                    error=f"HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            payload = json.loads(response.body_text or "{}")
            organic = payload.get("organic_results") if isinstance(payload, dict) else None
            hits: list[SearchHit] = []
            if isinstance(organic, list):
                for item in organic:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or "result").strip()[:160]
                    snippet = str(item.get("snippet") or "").strip()[:800]
                    url = item.get("link") or item.get("url")
                    hits.append(
                        SearchHit(
                            title=title,
                            snippet=snippet,
                            url=str(url)[:2048] if isinstance(url, str) else None,
                            source="serpapi",
                        )
                    )
                    if len(hits) >= limit:
                        break
            return SearchBundle(
                provider=self.name,
                real=True,
                results=tuple(hits),
                status_code=response.status_code,
            )
        except Exception as exc:
            return SearchBundle(provider=self.name, real=False, error=str(exc))


def _settings_provider_name() -> str:
    try:
        from backend.app.config import get_settings

        return str(get_settings().public_search_provider or "auto").strip().lower()
    except Exception:
        return (os.environ.get("AJENDA_PUBLIC_SEARCH_PROVIDER") or "auto").strip().lower()


def _brave_key() -> str:
    try:
        from backend.app.config import get_settings

        return str(get_settings().brave_search_api_key or "").strip()
    except Exception:
        return (os.environ.get("AJENDA_BRAVE_SEARCH_API_KEY") or "").strip()


def _serpapi_key() -> str:
    try:
        from backend.app.config import get_settings

        return str(get_settings().serpapi_api_key or "").strip()
    except Exception:
        return (os.environ.get("AJENDA_SERPAPI_API_KEY") or "").strip()


def resolve_public_search_provider_chain(*, preferred: str | None = None) -> list[PublicSearchProvider]:
    """Ordered providers to try until one returns real results (or real empty)."""

    name = (preferred or _settings_provider_name() or "auto").strip().lower()
    brave_key = _brave_key()
    serp_key = _serpapi_key()
    ddgs = DuckDuckGoSearchPackageProvider()
    instant = DuckDuckGoInstantAnswerProvider()
    brave = BraveSearchProvider(api_key=brave_key)
    serp = SerpApiSearchProvider(api_key=serp_key)

    if name == "brave":
        return [brave, ddgs, instant]
    if name == "serpapi":
        return [serp, ddgs, instant]
    if name == "ddgs":
        return [ddgs, instant]
    if name in {"duckduckgo_instant_answer", "instant", DEFAULT_SEARCH_PROVIDER}:
        return [instant, ddgs]
    # auto
    chain: list[PublicSearchProvider] = []
    if brave_key:
        chain.append(brave)
    if serp_key:
        chain.append(serp)
    chain.extend([ddgs, instant])
    return chain


def get_default_public_search_provider() -> PublicSearchProvider:
    """First provider in the configured chain (for tests / explicit single use)."""

    chain = resolve_public_search_provider_chain()
    return chain[0]


def public_search(
    *,
    query: str,
    limit: int = 5,
    timeout_seconds: float = 8.0,
    provider: PublicSearchProvider | None = None,
) -> SearchBundle:
    """Governed public search with provider failover."""

    if provider is not None:
        bundle = provider.search(query=query, limit=limit, timeout_seconds=timeout_seconds)
        return _stamp(bundle)

    last: SearchBundle | None = None
    attempts: list[str] = []
    for candidate in resolve_public_search_provider_chain():
        bundle = candidate.search(query=query, limit=limit, timeout_seconds=timeout_seconds)
        stamped = _stamp(bundle)
        attempts.append(
            f"{stamped.provider}:real={stamped.real}:n={len(stamped.results)}"
            + (f":err={stamped.error}" if stamped.error else "")
        )
        # Prefer real success with results; keep trying when empty or failed.
        if stamped.real and stamped.results:
            return stamped
        if stamped.real:
            last = stamped
            continue
        if last is None:
            last = stamped
    if last is None:
        return SearchBundle(
            provider="none",
            real=False,
            error="no search providers available; attempts=" + " | ".join(attempts),
        )
    # Surface failover chain when the winning bundle is empty/failed.
    if not last.results or not last.real:
        err = last.error or "empty results"
        return SearchBundle(
            provider=last.provider,
            real=last.real,
            results=last.results,
            status_code=last.status_code,
            error=f"{err}; attempts=" + " | ".join(attempts),
            access_mode=InternetAccessMode.PUBLIC_SEARCH,
        )
    return last


def _stamp(bundle: SearchBundle) -> SearchBundle:
    if bundle.access_mode == InternetAccessMode.PUBLIC_SEARCH:
        return bundle
    return SearchBundle(
        provider=bundle.provider,
        real=bundle.real,
        results=bundle.results,
        status_code=bundle.status_code,
        error=bundle.error,
        access_mode=InternetAccessMode.PUBLIC_SEARCH,
    )


def search_bundle_as_legacy_dict(bundle: SearchBundle) -> dict[str, Any]:
    """Shape expected by existing web.research / web.search output consumers."""

    payload = bundle.as_dict()
    return {
        "provider": payload["provider"],
        "real": payload["real"],
        "results": payload["results"],
        "result_count": payload["result_count"],
        "status_code": payload["status_code"],
        "error": payload["error"],
        "access_mode": payload["access_mode"],
    }
