"""Public web search providers — pluggable, chainable.

Priority (``AJENDA_PUBLIC_SEARCH_PROVIDER=auto``):
1. Brave Search API when ``AJENDA_BRAVE_SEARCH_API_KEY`` is set (egress)
2. SerpAPI when ``AJENDA_SERPAPI_API_KEY`` is set (egress)
3. DuckDuckGo HTML results via NetworkEgressAuthority
4. DuckDuckGo Instant Answer via NetworkEgressAuthority (fallback)

Brave, SerpAPI, and both DuckDuckGo providers use NetworkEgressAuthority. The
optional DDGS package owns its own HTTP client, so it is excluded from the
governed public-runtime chain.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from html.parser import HTMLParser
from itertools import zip_longest
from time import monotonic
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

from backend.services.internet.contracts import SearchAttempt, SearchBundle, SearchHit
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import get_default_network_egress_authority

DDG_INSTANT_ANSWER_HOST = "api.duckduckgo.com"
DDG_HTML_SEARCH_HOST = "html.duckduckgo.com"
DDG_REDIRECT_HOST = "duckduckgo.com"
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


_DDG_HTML_URL = f"https://{DDG_HTML_SEARCH_HOST}/html/"
_DDG_HTML_PREFERENCES = {"k1": "-1", "kav": "1"}
_DDG_HTML_MAX_PAGES = 3
_DDG_NEXT_FIELDS = frozenset({"q", "s", "dc", "vqd", "nextParams", "api", "o", "v", "kl", "df"})


class _DuckDuckGoHtmlResultParser(HTMLParser):
    """Read organic links and the Next form from one bounded HTML response."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[SearchHit] = []
        self.sponsored_rows_skipped = 0
        self.next_form: tuple[str, str, dict[str, str]] | None = None
        self._div_depth = 0
        self._sponsored_depth: int | None = None
        self._form: tuple[str, str, dict[str, str]] | None = None
        self._form_is_next = False
        self._href: str | None = None
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._snippet_end: tuple[str, int] | None = None
        self._snippet_target: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "div":
            self._div_depth += 1
            if "result" in classes:
                self._snippet_end = None
                self._snippet_target = None
            if self._sponsored_depth is None and classes & {"result--ad", "result--sponsored", "result--ad--small"}:
                self._sponsored_depth = self._div_depth
                self.sponsored_rows_skipped += 1

        if tag == "form":
            self._form = (values.get("method", "get").lower(), values.get("action", ""), {})
            self._form_is_next = False
        elif self._form is not None and tag == "input":
            name = values.get("name", "")
            input_type = values.get("type", "").lower()
            value = values.get("value", "")
            if input_type == "hidden" and name in _DDG_NEXT_FIELDS:
                self._form[2][name] = value
            elif input_type == "submit" and value.casefold().startswith("next"):
                self._form_is_next = True

        if self._sponsored_depth is not None:
            return
        if tag == "a" and "result__a" in classes:
            self._snippet_target = None
            href = values.get("href", "").strip()
            try:
                link = urlparse(urljoin(_DDG_HTML_URL, href))
                host = (link.hostname or "").lower().rstrip(".")
            except ValueError:
                return
            if (host == DDG_REDIRECT_HOST or host.endswith(f".{DDG_REDIRECT_HOST}")) and link.path.rstrip("/") in {
                "/aclick",
                "/y.js",
            }:
                self.sponsored_rows_skipped += 1
                return
            self._href = href or None
            self._title = []
        elif self._snippet_target is not None and tag in {"a", "div"} and "result__snippet" in classes:
            self._snippet_end = (tag, self._div_depth)
            self._snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            if self._form_is_next and self.next_form is None:
                self.next_form = self._form
            self._form = None
        if tag == "a" and self._href:
            title = " ".join("".join(self._title).split())
            try:
                url = _unwrap_duckduckgo_result_url(self._href)
            except ValueError:
                url = None
            if title and url:
                self._snippet_target = len(self.hits)
                self.hits.append(SearchHit(title=title[:160], snippet="", url=url, source="duckduckgo_html"))
            self._href = None
        if self._snippet_end == (tag, self._div_depth) and self._snippet_target is not None:
            index = self._snippet_target
            snippet = " ".join("".join(self._snippet).split())
            self.hits[index] = replace(self.hits[index], snippet=snippet[:800])
            self._snippet_end = None
            self._snippet_target = None
        if tag == "div":
            if self._sponsored_depth == self._div_depth:
                self._sponsored_depth = None
            self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._href:
            self._title.append(data)
        if self._snippet_end is not None:
            self._snippet.append(data)


def _ddg_next_page(
    form: tuple[str, str, dict[str, str]] | None, *, query: str, previous_offset: int
) -> tuple[str, str, int] | None:
    if form is None:
        return None
    method, action, fields = form
    try:
        target = urljoin(_DDG_HTML_URL, action)
        offset = int(fields.get("s", ""))
    except ValueError:
        return None
    if (
        method not in {"get", "post"}
        or target != _DDG_HTML_URL
        or fields.get("q") != query
        or not fields.get("vqd")
        or offset <= previous_offset
    ):
        return None
    return method.upper(), urlencode({**fields, **_DDG_HTML_PREFERENCES}), offset


def _unwrap_duckduckgo_result_url(raw_url: str) -> str | None:
    """Extract an HTTPS destination from DuckDuckGo's documented result wrapper.

    The wrapper is search-provider transport evidence, not a business source.
    Only the ``uddg`` query parameter on DuckDuckGo's redirect host is
    unwrapped; every other URL remains untouched and is later independently
    vetted before page observation.
    """

    candidate = raw_url.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlparse(candidate)
    if parsed.hostname and parsed.hostname.lower().rstrip(".") == DDG_REDIRECT_HOST and parsed.path == "/l/":
        destination = parse_qs(parsed.query).get("uddg", [""])[0].strip()
        destination_parsed = urlparse(destination)
        if destination_parsed.scheme == "https" and destination_parsed.hostname:
            return destination
        return None
    if parsed.scheme == "https" and parsed.hostname:
        return candidate
    return None


class DuckDuckGoHtmlSearchProvider:
    """General DuckDuckGo HTML results through the shared egress authority."""

    name = "duckduckgo_html"

    def search(self, *, query: str, limit: int, timeout_seconds: float) -> SearchBundle:
        query = query.strip()
        encoded = urlencode({"q": query, **_DDG_HTML_PREFERENCES})
        method, offset = "GET", 0
        deadline = monotonic() + min(timeout_seconds, 15.0)
        batches: list[list[SearchHit]] = []
        seen_urls: set[str | None] = set()
        sponsored_rows_skipped = 0
        status_code: int | None = None
        error: str | None = None
        remaining = deadline - monotonic()
        for _ in range(_DDG_HTML_MAX_PAGES):
            if remaining <= 0:
                error = "search time budget exhausted"
                break
            headers = {
                "User-Agent": "AjendaInternet/1.0 (+public_search/duckduckgo_html)",
                "Accept": "text/html,application/xhtml+xml",
            }
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                headers["Referer"] = f"https://{DDG_HTML_SEARCH_HOST}/"
            try:
                _dest, response = get_default_network_egress_authority().request(
                    method=method,
                    url=f"{_DDG_HTML_URL}?{encoded}" if method == "GET" else _DDG_HTML_URL,
                    headers=headers,
                    content=encoded.encode() if method == "POST" else None,
                    allowed_hosts=[DDG_HTML_SEARCH_HOST],
                    action_name="web.search",
                    timeout_seconds=remaining,
                    response_text_limit=524_288,
                )
                status_code = response.status_code
                body = response.body_text or ""
                challenge_markers = ("captcha", "verify you are human", "unusual traffic", "anomaly detected")
                if not 200 <= status_code < 300:
                    error = f"HTTP {status_code}"
                    break
                if any(marker in body.casefold() for marker in challenge_markers):
                    error = "provider challenge response"
                    break
                if response.body_truncated:
                    error = "response truncated before result parse"
                    break
                parser = _DuckDuckGoHtmlResultParser()
                parser.feed(body)
                parser.close()
            except Exception as exc:
                error = str(exc)
                break

            sponsored_rows_skipped += parser.sponsored_rows_skipped
            page: list[SearchHit] = []
            for hit in parser.hits:
                if hit.url not in seen_urls:
                    seen_urls.add(hit.url)
                    page.append(hit)
            batches.append(page)
            # Include a second batch even when the first fills the result
            # limit, so a directory-heavy first page cannot use every slot.
            if limit <= 1 or (len(batches) >= 2 and len(seen_urls) >= limit):
                break
            continuation = _ddg_next_page(parser.next_form, query=query, previous_offset=offset)
            if continuation is None:
                break
            method, encoded, offset = continuation
            remaining = deadline - monotonic()

        results = tuple(hit for rank in zip_longest(*batches) for hit in rank if hit is not None)[:limit]
        return SearchBundle(
            provider=self.name,
            real=bool(results) or (bool(batches) and error is None),
            results=results,
            status_code=status_code,
            error=error,
            pages_fetched=len(batches),
            sponsored_rows_skipped=sponsored_rows_skipped,
        )


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
    """Return only providers whose transport is governed by Ajenda egress.

    The optional DDGS package owns its own socket transport.  It remains an
    implementation artifact for callers that explicitly use it outside this
    public-runtime path, but it is not admissible for a governed mission
    search.  An explicit ``ddgs`` preference therefore falls through to the
    equivalent governed DuckDuckGo HTML endpoint instead of silently opening
    package-managed connections.
    """

    name = (preferred or _settings_provider_name() or "auto").strip().lower()
    brave_key = _brave_key()
    serp_key = _serpapi_key()
    html = DuckDuckGoHtmlSearchProvider()
    instant = DuckDuckGoInstantAnswerProvider()
    brave = BraveSearchProvider(api_key=brave_key)
    serp = SerpApiSearchProvider(api_key=serp_key)

    if name == "brave":
        return [brave, html, instant]
    if name == "serpapi":
        return [serp, html, instant]
    if name == "ddgs":
        return [html, instant]
    if name in {"duckduckgo_html", "html"}:
        return [html, instant]
    if name in {"duckduckgo_instant_answer", "instant", DEFAULT_SEARCH_PROVIDER}:
        return [instant]
    # auto
    chain: list[PublicSearchProvider] = []
    if brave_key:
        chain.append(brave)
    if serp_key:
        chain.append(serp)
    chain.extend([html, instant])
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
        return _with_attempt(_stamp(bundle), ())

    last: SearchBundle | None = None
    attempts: list[SearchAttempt] = []
    for candidate in resolve_public_search_provider_chain():
        bundle = candidate.search(query=query, limit=limit, timeout_seconds=timeout_seconds)
        stamped = _stamp(bundle)
        attempts.append(
            SearchAttempt(
                provider=stamped.provider,
                outcome="results" if stamped.real and stamped.results else "empty" if stamped.real else "failure",
                result_count=len(stamped.results),
                status_code=stamped.status_code,
                error=stamped.error,
                pages_fetched=stamped.pages_fetched,
                sponsored_rows_skipped=stamped.sponsored_rows_skipped,
            )
        )
        # Prefer real success with results; keep trying when empty or failed.
        if stamped.real and stamped.results:
            return _with_attempt(stamped, attempts)
        if stamped.real:
            last = stamped
            continue
        if last is None:
            last = stamped
    if last is None:
        return SearchBundle(
            provider="none",
            real=False,
            error="no governed search providers available",
            attempts=tuple(attempts),
        )
    # A real empty response is a successful observation, not a provider error.
    # Earlier provider failures remain reconstructable in ``attempts``.
    if not last.real:
        err = last.error or "empty results"
        return SearchBundle(
            provider=last.provider,
            real=last.real,
            results=last.results,
            status_code=last.status_code,
            error=err,
            access_mode=InternetAccessMode.PUBLIC_SEARCH,
            attempts=tuple(attempts),
        )
    return _with_attempt(last, attempts)


def _stamp(bundle: SearchBundle) -> SearchBundle:
    if bundle.access_mode == InternetAccessMode.PUBLIC_SEARCH:
        return bundle
    return replace(bundle, access_mode=InternetAccessMode.PUBLIC_SEARCH)


def _with_attempt(bundle: SearchBundle, attempts: tuple[SearchAttempt, ...] | list[SearchAttempt]) -> SearchBundle:
    """Attach complete chain provenance without encoding it into error text."""

    if bundle.attempts:
        return bundle
    if not attempts:
        attempts = (
            SearchAttempt(
                provider=bundle.provider,
                outcome="results" if bundle.real and bundle.results else "empty" if bundle.real else "failure",
                result_count=len(bundle.results),
                status_code=bundle.status_code,
                error=bundle.error,
                pages_fetched=bundle.pages_fetched,
                sponsored_rows_skipped=bundle.sponsored_rows_skipped,
            ),
        )
    return replace(bundle, attempts=tuple(attempts))


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
        "attempts": payload["attempts"],
        "access_mode": payload["access_mode"],
    }
