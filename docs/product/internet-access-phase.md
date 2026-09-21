# Internet Access Phase — Progressive Open-Web Value

**Status:** Active (combined lane shipped)  
**Last updated:** 2026-07-27  
**Source of truth:** `backend/services/internet/`, registered actions, tests, `scripts/validation/internet_live_proof.py`

## Purpose

Give Ajenda real public-internet leverage on the governed runtime spine.

- Connector OAuth (Gmail, Calendar, CRM) stays a **separate credential lane**.
- Public internet is the **open-web lane**.

## Modes

| Mode | Action(s) | Gate | Behavior |
|------|-----------|------|----------|
| `public_search` | `web.search`, `web.research` | always | Provider chain: Brave → SerpAPI → ddgs → DDG Instant Answer |
| `page_read` | `web.page_read` | always | Single HTTPS GET + HTML extract |
| `http_request` | `http.request` | always | Governed HTTP; writes need side-effect auth |
| `browser_session` | `web.browser_session` | `AJENDA_BROWSER_SESSION_ENABLED` | Ephemeral Playwright Chromium; bounded read-only steps; destroy after call |
| `open_write` | `web.open_write` | `AJENDA_OPEN_WRITE_ENABLED` | POST/PUT/PATCH + idempotency + hourly rate limit |

## Env

```bash
# Search (auto picks strongest available)
AJENDA_PUBLIC_SEARCH_PROVIDER=auto   # auto|ddgs|duckduckgo_instant_answer|brave|serpapi
AJENDA_BRAVE_SEARCH_API_KEY=
AJENDA_SERPAPI_API_KEY=

# Prototypes (fail closed when false)
AJENDA_BROWSER_SESSION_ENABLED=false
AJENDA_OPEN_WRITE_ENABLED=false
AJENDA_OPEN_WRITE_MAX_PER_HOUR=20
```

## Browser isolation rule

1. Vet the start URL and every requested origin with `NetworkEgressAuthority.vet_https_url` before Chromium starts.
2. Launch browser + **new context** for this call only.
3. Execute at most 12 declared read-only steps (`navigate`, `observe`, `extract`); no authentication or external writes.
4. Re-vet redirects, frames, and subresources against the origin allow-list.
5. Close context and browser in `finally` — never reuse across tenants or leases.

## Open write

- Idempotency key **required** on every invocation.
- Per-tenant fixed window: `AJENDA_OPEN_WRITE_MAX_PER_HOUR` / 3600s.
- No raw credential headers (schema reject).
- HTTPS-only egress; evidence records `real`, status, rate_limit_remaining.

## Live proof

```bash
python scripts/validation/internet_live_proof.py
# optional:
AJENDA_BROWSER_SESSION_ENABLED=true python scripts/validation/internet_live_proof.py --browser
AJENDA_OPEN_WRITE_ENABLED=true python scripts/validation/internet_live_proof.py --open-write
```

Exit 0 requires at least one of search / page_read with `real: true` when network is available.

## Runtime support

The project pins Playwright in `pyproject.toml`. The worker image installs the matching Chromium binary under
`/ms-playwright`; a worker image without that dependency must fail the browser readiness proof rather than silently
claiming browser capability.

## Non-goals

- Autonomous browser agent loop or unbounded browser planning
- Sharing Chromium across workers/tenants
- Using public internet as a substitute for connector OAuth
