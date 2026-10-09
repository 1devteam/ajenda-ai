"""Research, web, browser, and public-observation action input builders."""

from __future__ import annotations

import re
from typing import Any

from backend.services.ajenda_demo_fixtures import local_fixture_scope_keys

from backend.services.mission_composition.action_input_common import (
    _SCRAPE_SITE_RE,
    _ajenda_internal_crm_only,
    _compact_research_query,
    _extract_company_from_instruction,
    _instruction_text,
    _local_fixture_only,
    has_usable_research_scope,
)
from backend.services.mission_composition.contracts import MissionIntent

def build_research_action_input(*, action_name: str, intent: MissionIntent) -> dict[str, Any] | None:
    industry, location, query = _target_bits(intent)
    limit = _prospect_count(intent)
    primary_entity = intent.target_entities[0] if intent.target_entities else None
    if action_name == "web.research":
        if not has_usable_research_scope(intent):
            raise ValueError(
                "web.research requires industry, location, named company, or competitor set; refusing placeholder query"
            )
        entity = intent.target_entities[0] if intent.target_entities else None
        source = _instruction_text(intent)
        research_query = _compact_research_query(intent)
        # Prefer structured industry/location phrasing when both present.
        if entity and entity.industry and entity.location and not entity.name:
            research_query = f"{entity.industry} companies in {entity.location}"
        extracted_company = (
            (entity.name.strip() if entity and entity.name else None)
            or industry
            or _extract_company_from_instruction(source)
        )
        domain = entity.domain if entity and entity.domain else None
        if domain is None and entity and isinstance(entity.attributes, dict):
            for key in ("domain", "website", "url"):
                raw = entity.attributes.get(key)
                if isinstance(raw, str) and raw.strip():
                    domain = raw.strip()
                    break
        if isinstance(domain, str) and domain and "://" in domain:
            from urllib.parse import urlparse

            domain = urlparse(domain).netloc.removeprefix("www.") or domain
        scrape_intent = bool(_SCRAPE_SITE_RE.search(source))
        # Site-scoped research when user asked to scrape/visit a website and we have a host.
        fetch_public_page = bool(scrape_intent and domain)
        # When scrape intent names a company but no host yet, still flag fetch so the
        # handler can use an explicit host from the query if present.
        if scrape_intent and extracted_company and not domain:
            fetch_public_page = True
        local_fixture_only = bool(
            re.search(r"\blocal\s+(?:test\s+)?fixtures?\b|\bfixture\s+data\s+only\b", source, re.IGNORECASE)
        )
        if local_fixture_only and entity and entity.industry and entity.location:
            fixture_scope_supported = (
                " ".join(entity.industry.casefold().split()),
                " ".join(entity.location.casefold().split()),
            ) in local_fixture_scope_keys()
            if not fixture_scope_supported:
                raise ValueError(
                    "local prospect fixtures require a configured industry/location scope; "
                    "requested fixture scope is unavailable"
                )
        internal_crm_only = _ajenda_internal_crm_only(intent)
        internal_only = local_fixture_only or internal_crm_only
        return {
            "query": research_query[:400],
            "company": extracted_company,
            "domain": domain,
            "fetch_public_page": fetch_public_page,
            "include_public_search": not internal_only,
            "local_fixture_only": internal_only,
            "limit": limit,
        }
    if action_name == "web.search":
        if not has_usable_research_scope(intent):
            raise ValueError(
                "web.search requires industry, location, named company, or competitor set; refusing placeholder query"
            )
        return {"query": _compact_research_query(intent)[:400], "limit": limit}
    if action_name == "research.observe_contacts":
        # Ajenda-internal CRM research resolves contacts from tenant-scoped
        # records rather than requiring public source pages.
        local_fixture_only = _local_fixture_only(intent) or _ajenda_internal_crm_only(intent)
        return {
            "prospects": [],
            "requested_quantity": limit,
            "timeout_seconds": 8.0,
            "binding_required": True,
            "local_fixture_only": local_fixture_only,
            "context": {
                "binding_required": True,
                "binding_source": "upstream_prospect_candidates",
                "objective": intent.objective,
                "requested_quantity": limit,
                "source": (
                    "internal_crm"
                    if _ajenda_internal_crm_only(intent)
                    else "external_crm"
                    if "hubspot_source" in intent.context_requirements
                    else "local_fixture"
                ),
            },
        }
    if action_name == "research.verify_public_identity":
        primary = intent.target_entities[0] if intent.target_entities else None
        attrs = primary.attributes if primary and isinstance(primary.attributes, dict) else {}
        source = _instruction_text(intent)

        def _labeled_value(label: str) -> str:
            match = re.search(rf"\b{label}\s*:\s*([^.;,\n]+)", source, flags=re.IGNORECASE)
            return match.group(1).strip() if match else ""

        candidate_url = str(attrs.get("url") or attrs.get("website") or attrs.get("domain") or "").strip()
        if not candidate_url:
            match = re.search(r"https?://[^\s<>()]+", source, flags=re.IGNORECASE)
            candidate_url = match.group(0).rstrip(".,;:") if match else ""
        if candidate_url and "://" not in candidate_url:
            candidate_url = f"https://{candidate_url.lstrip('.')}"
        expected_company = str(
            attrs.get("expected_company") or attrs.get("company") or attrs.get("name") or ""
        ).strip() or _labeled_value("expected company")
        industry = str(attrs.get("industry") or "").strip() or _labeled_value("industry")
        location = str(attrs.get("location") or "").strip() or _labeled_value("location")
        if not candidate_url or not expected_company or not industry or not location:
            raise ValueError(
                "research.verify_public_identity requires target URL, expected company, industry, and location"
            )
        return {
            "url": candidate_url,
            "expected_company": expected_company,
            "industry": industry,
            "location": location,
            "timeout_seconds": 15.0,
        }
    if action_name in {"web.page_read", "web.browser_session"}:
        # Prefer domain-like attributes on target entities when present.
        # Never invent example.com — missing URL fails closed at composition.
        url: str | None = None
        for entity in intent.target_entities:
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            candidate = str(attrs.get("domain") or attrs.get("website") or attrs.get("url") or entity.url or "").strip()
            if candidate:
                url = candidate if "://" in candidate else f"https://{candidate.lstrip('.')}"
                break
        if not url:
            # Scrape-style instructions with an explicit host in free text.
            source = _instruction_text(intent)
            host_match = re.search(
                r"https?://[^\s<>()]+|\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b",
                source,
                flags=re.IGNORECASE,
            )
            if host_match is not None:
                raw_host = host_match.group(0).strip()
                url = raw_host if "://" in raw_host else f"https://{raw_host.removeprefix('www.')}"
        if not url:
            raise ValueError(
                f"{action_name} requires a target URL (entity attributes domain, website, or url); "
                "refusing to synthesize example.com"
            )
        if action_name == "web.browser_session":
            attrs = primary_entity.attributes if primary_entity and isinstance(primary_entity.attributes, dict) else {}
            raw_requirements = attrs.get("observation_requirements")
            requirements: list[dict[str, Any]] = []
            if isinstance(raw_requirements, list):
                for item in raw_requirements:
                    if isinstance(item, dict) and isinstance(item.get("kind"), str):
                        requirement = {"kind": item["kind"]}
                        if isinstance(item.get("selector"), str):
                            requirement["selector"] = item["selector"]
                        if isinstance(item.get("min_length"), int):
                            requirement["min_length"] = item["min_length"]
                        requirements.append(requirement)
            if not requirements:
                requirements = [{"kind": "title"}, {"kind": "body"}]
            commands: list[dict[str, Any]] = []
            source = _instruction_text(intent)
            selector_request = re.search(
                r"\bextract\s+(?:the\s+)?(?:text|value)\s+from\s+(?:the\s+)?(?:css\s+)?selector\s+"
                r"(?P<quote>[\"'`])(?P<selector>[^\"'`]{1,512})(?P=quote)",
                source,
                flags=re.IGNORECASE,
            )
            if selector_request is not None:
                selector = selector_request.group("selector").strip()
                if selector and not any(
                    item.get("kind") == "selector_text" and item.get("selector") == selector for item in requirements
                ):
                    requirements.append({"kind": "selector_text", "selector": selector})
            navigate_request = re.search(
                r"\bnavigate\s+to\s+(?P<url>https?://[^\s<>()]+)",
                source,
                flags=re.IGNORECASE,
            )
            if navigate_request is not None:
                target_url = navigate_request.group("url").rstrip(".,;:!?)]}")
                if target_url:
                    commands.append({"action": "navigate", "url": target_url})
            follow_match = re.search(
                r"\bfollow\b[^.!?]{0,100}\blink\b",
                source,
                flags=re.IGNORECASE,
            )
            quoted_link = re.search(r"[\"“](.+?)[\"”]", source)
            if follow_match and quoted_link:
                link_text = quoted_link.group(1).strip().rstrip("…").rstrip(".").strip()
                if link_text:
                    # Match one exact visible label while tolerating punctuation the
                    # instruction omitted. A broad :has-text selector can resolve
                    # multiple links and makes Playwright strict-mode selection fail.
                    link_pattern = rf"^\s*{re.escape(link_text)}\s*(?:[….]*)?$"
                    escaped_pattern = link_pattern.replace("\\", "\\\\").replace('"', '\\"')
                    commands.append(
                        {
                            "action": "click",
                            "selector": f'a:text-matches("{escaped_pattern}", "i")',
                        }
                    )
            for requirement in requirements:
                if requirement["kind"] in {"title", "body"}:
                    if not any(command.get("action") == "observe" for command in commands):
                        commands.append({"action": "observe"})
                elif requirement["kind"] == "selector_text":
                    commands.append({"action": "extract", "selector": requirement["selector"]})
            return {
                "url": url,
                "timeout_seconds": 15.0,
                "allowed_origins": [url],
                "commands": commands,
                "observation_requirements": requirements,
            }
        return {"url": url, "timeout_seconds": 8.0}
    if action_name == "http.request":
        return {"method": "GET", "url": "https://example.com", "timeout_seconds": 5.0}
    return None
