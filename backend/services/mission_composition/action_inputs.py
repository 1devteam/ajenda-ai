"""Derive non-empty tool.invoke inputs from MissionIntent for composed graphs."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.mission_composition.contracts import MissionIntent, is_ranking_only_instruction

_DEFAULT_PROSPECT_COUNT = 3
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_NAMED_DAY = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
_ISO_DAY = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")


def _calendar_window_from_objective(objective: str) -> tuple[str | None, str | None]:
    """Return ISO start/end for a named day when present (UTC day bounds)."""

    text = (objective or "").strip()
    if not text:
        return None, None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    named = _NAMED_DAY.search(text)
    if named is not None:
        month = _MONTHS.get(named.group("month").lower())
        day = int(named.group("day"))
        year_raw = named.group("year")
        year = int(year_raw) if year_raw else datetime.now(tz=UTC).year
    else:
        iso = _ISO_DAY.search(text)
        if iso is not None:
            year = int(iso.group("year"))
            month = int(iso.group("month"))
            day = int(iso.group("day"))
    if not year or not month or not day:
        return None, None
    try:
        start = datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
    except ValueError:
        return None, None
    end = start + timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _prospect_count(intent: MissionIntent) -> int:
    """Use structured quantity only — never reparse success-criteria prose."""

    if intent.requested_quantity is not None:
        return max(1, min(int(intent.requested_quantity), 20))
    return _DEFAULT_PROSPECT_COUNT


def _research_query_fallback(intent: MissionIntent) -> str:
    """Build a compact search query from entities + instruction — not a verb dump."""

    return _compact_research_query(intent)


_SCRAPE_SITE_RE = re.compile(
    r"\b(?:scrape|crawl|visit|open|read)\b.{0,40}\b(?:web\s*site|website|site|page|url)\b|"
    r"\b(?:web\s*site|website)\b",
    re.IGNORECASE,
)
_PERSON_AFTER_ROLE_RE = re.compile(
    r"\b(?:quality\s+control|qc|contact|find|for)\s+"
    r"(?P<person>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
)
_SCRAPE_COMPANY_RE = re.compile(
    r"\b(?:scrape|crawl|visit|open)\s+(?:the\s+)?"
    r"(?P<company>[A-Za-z0-9][A-Za-z0-9.&'\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-]*){0,4}?)"
    r"\s+(?:web\s*site|website|site|page)\b",
    re.IGNORECASE,
)
_COMPANY_WEBSITE_RE = re.compile(
    r"\b(?P<company>[A-Za-z0-9][A-Za-z0-9.&'\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-]*){0,4}?)"
    r"\s+(?:web\s*site|website)\b",
    re.IGNORECASE,
)
_STOP_QUERY_VERBS = re.compile(
    r"\b(?:scrape|crawl|return|find|get|give|show|need|want|please|research|"
    r"identify|locate|look\s+up|look\s+for)\b",
    re.IGNORECASE,
)


def _instruction_text(intent: MissionIntent) -> str:
    return (intent.raw_instruction or intent.normalized_instruction or intent.objective or "").strip()


_GITHUB_OWNER_REPO = re.compile(
    r"\bgithub\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b|"
    r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b"
)


_PLACEHOLDER_RESEARCH_QUERIES = frozenset(
    {
        "companies",
        "businesses",
        "prospects",
        "leads",
        "prospect research",
    }
)


def has_usable_research_scope(intent: MissionIntent) -> bool:
    """True when discovery has a real market, company, or competitor — not a placeholder query."""

    if any(item.field == "target_scope" for item in intent.ambiguity):
        return False
    for entity in intent.target_entities:
        if entity.industry or entity.location or entity.domain or entity.url:
            return True
        if entity.name and entity.type in {"company", "person", "competitor_set", "contact"}:
            return True
        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        if attrs.get("research_mode") == "competitors" and (entity.name or attrs.get("seed_company")):
            return True
    source = _instruction_text(intent)
    if _extract_company_from_instruction(source) or _extract_person_from_instruction(source):
        return True
    query = _compact_research_query(intent).strip().casefold()
    return bool(query) and query not in _PLACEHOLDER_RESEARCH_QUERIES


def extract_github_owner_repo(intent: MissionIntent) -> tuple[str, str] | None:
    """Return owner/repo from structured entities or instruction text. Never invents 'pending'."""

    for entity in intent.target_entities:
        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        if attrs.get("github_owner") and attrs.get("github_repo"):
            return str(attrs["github_owner"]), str(attrs["github_repo"])
        if entity.type == "github_repo" and entity.name and "/" in entity.name:
            parts = entity.name.strip("/").split("/", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]
    match = _GITHUB_OWNER_REPO.search(_instruction_text(intent))
    if match is None:
        return None
    owner = match.group(1) or match.group(3)
    repo = match.group(2) or match.group(4)
    if not owner or not repo:
        return None
    return owner, repo


def _local_fixture_only(intent: MissionIntent) -> bool:
    """Read the fixture constraint from the original instruction, not the objective summary."""

    return bool(
        re.search(
            r"\blocal\s+(?:test\s+)?fixtures?\b|\bfixture\s+data\s+only\b",
            _instruction_text(intent),
            re.IGNORECASE,
        )
        or _ajenda_internal_crm_only(intent)
    )


def _ajenda_internal_crm_only(intent: MissionIntent) -> bool:
    """Keep explicitly Ajenda-internal CRM research off public search."""

    return bool(
        re.search(
            r"\b(?:ajenda(?:'s)?\s+internal\s+crm|internal\s+ajenda\s+crm|ajenda\s+internal\s+(?:crm\s+)?records?)\b",
            _instruction_text(intent),
            re.IGNORECASE,
        )
    )


def _extract_person_from_instruction(text: str) -> str | None:
    match = _PERSON_AFTER_ROLE_RE.search(text or "")
    if match is None:
        return None
    person = match.group("person").strip(" ,.;:")
    if person.casefold() in {"quality control", "contact info", "contact information"}:
        return None
    return person[:120] if len(person) >= 3 else None


def _extract_company_from_instruction(text: str) -> str | None:
    for pattern in (_SCRAPE_COMPANY_RE, _COMPANY_WEBSITE_RE):
        match = pattern.search(text or "")
        if match is None:
            continue
        company = match.group("company").strip(" ,.;:")
        # Drop leading articles / verbs left on the capture.
        company = re.sub(r"^(?:the|a|an)\s+", "", company, flags=re.IGNORECASE).strip()
        if company.casefold() in {"the", "a", "an", "web", "their", "our", "its"}:
            continue
        if len(company) >= 2:
            return company[:160]
    return None


def _compact_research_query(intent: MissionIntent) -> str:
    """Entity-first search string. Avoid dumping the full mission as a DDG query."""

    entity = intent.target_entities[0] if intent.target_entities else None
    industry = entity.industry.strip() if entity and entity.industry else None
    location = entity.location.strip() if entity and entity.location else None
    name = entity.name.strip() if entity and entity.name else None
    source = _instruction_text(intent)
    person = _extract_person_from_instruction(source)
    company = name or _extract_company_from_instruction(source)

    if entity and (
        entity.type == "competitor_set"
        or (isinstance(entity.attributes, dict) and entity.attributes.get("research_mode") == "competitors")
    ):
        if name and location:
            return f"competitors of {name} in {location}"[:400]
        if name:
            return f"competitors of {name}"[:400]

    parts: list[str] = []
    if company:
        parts.append(company)
    if person:
        parts.append(person)
        if re.search(r"\bquality\s+control\b|\bqc\b", source, flags=re.IGNORECASE):
            parts.append("quality control")
        if re.search(r"\bcontact\b", source, flags=re.IGNORECASE):
            parts.append("contact")
    if industry and industry.casefold() not in " ".join(parts).casefold():
        parts.append(industry)
    if location and location.casefold() not in " ".join(parts).casefold():
        parts.append(location)
    if company and _SCRAPE_SITE_RE.search(source):
        parts.append("official website")
    if parts:
        return " ".join(parts)[:400]

    # Last resort: strip imperative verbs from instruction rather than full dump.
    cleaned = _STOP_QUERY_VERBS.sub(" ", source)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:")
    if cleaned and len(cleaned) >= 8:
        return cleaned[:400]
    return "prospect research"


def _target_bits(intent: MissionIntent) -> tuple[str | None, str | None, str]:
    entity = intent.target_entities[0] if intent.target_entities else None
    industry = entity.industry.strip() if entity and entity.industry else None
    location = entity.location.strip() if entity and entity.location else None
    if entity and (
        entity.type == "competitor_set"
        or (isinstance(entity.attributes, dict) and entity.attributes.get("research_mode") == "competitors")
    ):
        name = (entity.name or "").strip()
        if name and location:
            return industry, location, f"competitors of {name} in {location}"
        if name:
            return industry, location, f"competitors of {name}"
    parts: list[str] = []
    if industry:
        parts.append(industry)
    parts.append("companies")
    if location:
        parts.append(f"in {location}")
    query = " ".join(parts).strip()
    if not query or query == "companies":
        query = _compact_research_query(intent)
    return industry, location, query


def _explicit_email(intent: MissionIntent) -> str | None:
    """Return a concrete recipient email from structured entities, if any."""

    for entity in intent.target_entities:
        if entity.email and "@" in entity.email:
            return entity.email.strip()
        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        for key in ("email", "recipient_email", "to"):
            value = attrs.get(key)
            if isinstance(value, str) and "@" in value:
                return value.strip()
        if entity.type in {"email", "recipient", "contact"} and entity.name and "@" in entity.name:
            return entity.name.strip()
    return None


def _source_instruction(intent: MissionIntent) -> str:
    return (intent.raw_instruction or intent.normalized_instruction or intent.objective or "").strip()


def _gmail_query(intent: MissionIntent) -> str:
    """Build a bounded Gmail search query from explicit read-only language.

    Imperative \"read messages\" is not a Gmail is:read filter. Material search
    terms (from, subject keywords) are compiled when possible; otherwise fail closed.
    """

    source = _source_instruction(intent)
    lower = source.lower()
    terms: list[str] = []
    if re.search(r"\b(?:sent|outbox)\b", lower):
        terms.append("in:sent")
    else:
        terms.append("in:inbox")
    if "unread" in lower:
        terms.append("is:unread")
    elif re.search(r"\b(?:already\s+read|is\s+read|read\s+only)\b", lower):
        # Only explicit read-state language — not the verb "read my email".
        terms.append("is:read")
    if re.search(r"\b(?:last|past)\s+week\b", lower):
        terms.append("newer_than:7d")
    elif re.search(r"\b(?:last|past)\s+month\b", lower):
        terms.append("newer_than:30d")
    elif re.search(r"\btoday\b|\blast\s+24\s+hours?\b", lower):
        terms.append("newer_than:1d")

    from_email = re.search(
        r"\bfrom\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        source,
        flags=re.IGNORECASE,
    )
    if from_email is not None:
        terms.append(f"from:{from_email.group(1)}")
    else:
        # Stop sender capture before temporal / filter clauses (last week, unread, …).
        from_name = re.search(
            r"\bfrom\s+"
            r"([A-Za-z][A-Za-z\-']+"
            r"(?:\s+(?:and\s+)?[A-Za-z][A-Za-z\-']+){0,4}?)"
            r"(?=\s+(?:last|past|today|unread|newer|older|after|before|for|"
            r"about|regarding|containing|with|in:|is:|"
            r"and\s+(?:summarize|show|list|return|find|include|exclude)\b|,|$)|$)",
            source,
            flags=re.IGNORECASE,
        )
        if from_name is not None:
            name = from_name.group(1).strip()
            if name.lower() not in {
                "gmail",
                "google",
                "the",
                "my",
                "inbox",
                "last",
                "past",
                "this",
                "today",
            }:
                # Quote multiword names so Gmail treats them as one from: token.
                sender = f'"{name}"' if " " in name else name
                terms.append(f"from:{sender}")

    # Free-text after "for …" (e.g. "Search Gmail for Acme invoices").
    # Bound each clause at the next "for" so independent material constraints
    # are preserved while temporal-only clauses remain represented by date terms.
    for_clauses = list(re.finditer(r"\bfor\s+", source, flags=re.IGNORECASE))
    keyword_candidates: list[str] = []
    seen_keyword_candidates: set[str] = set()
    for index, clause in enumerate(for_clauses):
        clause_end = for_clauses[index + 1].start() if index + 1 < len(for_clauses) else len(source)
        rest = source[clause.end() : clause_end]
        rest = re.sub(
            r"\b(?:unread|replies?|messages?|emails?|mail)\b",
            " ",
            rest,
            flags=re.IGNORECASE,
        )
        rest = re.sub(
            r"\bfrom\s+(?:"
            r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|"
            r"[A-Za-z][A-Za-z\-']*(?:\s+[A-Za-z][A-Za-z\-']*){0,4}?"
            r")(?=\s+(?:for\b|about\b|regarding\b|containing\b|with\b|"
            r"last\b|past\b|today\b|unread\b|"
            r"and\s+(?:summarize|show|list|return|find|include|exclude)\b|$)|$)",
            " ",
            rest,
            flags=re.IGNORECASE,
        )
        rest = re.sub(
            r"\band\s+(?:summarize|show|list|return|find|include|exclude)\b.*$",
            " ",
            rest,
            flags=re.IGNORECASE,
        )
        rest = re.sub(r"^\s*(?:about|regarding|containing|with)\s+", " ", rest, flags=re.IGNORECASE)
        rest = re.sub(
            r"\b(?:last|past)\s+(?:week|month|day|24\s+hours?)\b|\btoday\b",
            " ",
            rest,
            flags=re.IGNORECASE,
        )
        rest = re.sub(r"(?:\bfor\s+)?\bthe\s*$", " ", rest, flags=re.IGNORECASE)
        rest = re.sub(r"^\s*for\s+", " ", rest, flags=re.IGNORECASE)
        rest = re.sub(r"\s+", " ", rest).strip(" ,.;")
        if rest and len(rest) >= 2 and rest.lower() not in {"a", "an", "the"}:
            keyword_candidate = rest[:80]
            normalized_candidate = keyword_candidate.casefold()
            if normalized_candidate not in seen_keyword_candidates:
                seen_keyword_candidates.add(normalized_candidate)
                keyword_candidates.append(keyword_candidate)
    for keyword_candidate in keyword_candidates:
        terms.append(f'"{keyword_candidate}"' if " " in keyword_candidate else keyword_candidate)

    # Material scopes we cannot compile → refuse silent full-inbox widen.
    residual = re.search(
        r"\b(?:subject:|has:attachment|label:|before:|after:|larger:|smaller:)\b",
        lower,
    )
    if residual is not None:
        raise ValueError(
            "Gmail search uses operators that composition cannot compile yet; "
            "restate with from:/unread/date window language or an explicit query string"
        )
    return " ".join(dict.fromkeys(terms))


def _salesforce_soql(intent: MissionIntent) -> str:
    """Build a conservative read-only SOQL query from explicit Salesforce language.

    Fail closed when the instruction states filters we cannot compile — never run an
    unfiltered object dump that silently ignores named/date scope.
    """

    source = _source_instruction(intent)
    explicit = re.search(r"\bSELECT\s+.+", source, flags=re.IGNORECASE | re.DOTALL)
    if explicit is not None:
        return explicit.group(0).strip().strip("\"'").rstrip(";")[:4000]

    lower = source.lower()
    if re.search(r"\bopportunit(?:y|ies)\b", lower):
        object_name = "Opportunity"
        fields = "Id, Name, Amount, StageName, CloseDate"
    elif re.search(r"\bcontacts?\b", lower):
        object_name = "Contact"
        fields = "Id, Name, Email, AccountId, LastModifiedDate"
    elif re.search(r"\bleads?\b", lower):
        object_name = "Lead"
        fields = "Id, Name, Company, Email, Status, LastModifiedDate"
    else:
        object_name = "Account"
        fields = "Id, Name, Industry, Website, LastModifiedDate"

    filters: list[str] = []
    if object_name == "Opportunity":
        if re.search(r"\bopen\b|\bactive\b|\bnot\s+closed\b", lower):
            filters.append("IsClosed = false")
        if re.search(r"\b(?:closing|close)\b.{0,24}\bthis\s+quarter\b", lower):
            filters.append("CloseDate = THIS_QUARTER")
        amount = re.search(
            r"\b(over|above|greater\s+than|at\s+least)\s+\$?([0-9][0-9,]*(?:\.[0-9]+)?)\s*([km])?\b",
            lower,
        )
        if amount is not None:
            value = float(amount.group(2).replace(",", ""))
            suffix = amount.group(3)
            if suffix == "k":
                value *= 1000
            elif suffix == "m":
                value *= 1_000_000
            operator = ">=" if amount.group(1) == "at least" else ">"
            filters.append(f"Amount {operator} {int(value)}")
    else:
        # Contact / Lead / Account — only compile filters we can express honestly.
        # Keep "and" inside names (Johnson and Johnson). Only stop at real filter openers.
        name_match = re.search(
            r"\b(?:named|called|name\s+is)\s+"
            r"([A-Za-z][A-Za-z\-']+(?:\s+(?:and\s+)?[A-Za-z][A-Za-z\-']+){0,4}?)"
            r"(?=\s+(?:modified|updated|changed|last|with|where|that\b|,|;|$)|$)",
            source,
            flags=re.IGNORECASE,
        )
        if name_match is not None:
            safe_name = name_match.group(1).strip().replace("'", "\\'")
            # Drop trailing conjunction fragments without a following name token.
            safe_name = re.sub(r"\s+and$", "", safe_name, flags=re.IGNORECASE).strip()
            if safe_name:
                filters.append(f"Name LIKE '%{safe_name}%'")
        days_match = re.search(
            r"\b(?:modified|updated|changed)\b.{0,24}\b(?:last|past)\s+(\d{1,3})\s+days?\b",
            lower,
        )
        if days_match is not None:
            days = max(1, min(int(days_match.group(1)), 365))
            filters.append(f"LastModifiedDate = LAST_N_DAYS:{days}")
        # Stated filter language we do not compile → fail closed (no silent unfiltered dump).
        residual_filter = re.search(
            r"\b(?:where|filter(?:ed)?|status\s+is|email\s+is|industry\s+is|owner\s+is|"
            r"with\s+status|matching\s+criteria)\b",
            lower,
        )
        if residual_filter is not None and not filters:
            raise ValueError(
                "Salesforce filter criteria in the instruction cannot be compiled safely; "
                "restate with an explicit SOQL SELECT or a supported named/date filter"
            )
        stated_scope = re.search(
            r"\b(?:named|called|name\s+is|modified|updated|changed|last\s+\d+\s+days)\b",
            lower,
        )
        if stated_scope is not None and not filters:
            raise ValueError(
                "Salesforce request states a record filter that was not compiled; refusing unfiltered object query"
            )

    soql = f"SELECT {fields} FROM {object_name}"
    if filters:
        soql += " WHERE " + " AND ".join(filters)
    if object_name == "Opportunity" and re.search(r"\btop\b|\blargest\b|\bhighest\b|\bamount\b", lower):
        soql += " ORDER BY Amount DESC"
    requested_limit = intent.requested_quantity if intent.requested_quantity is not None else 20
    soql += f" LIMIT {max(1, min(int(requested_limit), 50))}"
    return soql


def build_action_input(*, action_name: str, intent: MissionIntent, vertical_role: str | None = None) -> dict[str, Any]:
    """Return a schema-valid-enough input payload for the action.

    Downstream steps may still rebind outputs via input_bindings; this ensures
    tool.invoke does not fail closed on empty required fields (e.g. web.research.query).
    """

    industry, location, query = _target_bits(intent)
    limit = _prospect_count(intent)
    primary_entity = intent.target_entities[0] if intent.target_entities else None
    explicit_company = primary_entity.name.strip() if primary_entity and primary_entity.name else None
    company_label = explicit_company or industry or "prospect company"
    if location:
        company_label = f"{company_label} ({location})"

    lead: dict[str, Any] = {
        "company": company_label,
        "source": "mission_composition",
    }
    if industry:
        lead["industry"] = industry
    if location:
        lead["location"] = location

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
    if action_name == "research.synthesize_report":
        return {
            "objective": intent.objective[:1000],
            "prospects": [],
            # A synthesis node is only selected when the graph includes the
            # upstream research job. Never report synthetic success if that
            # dependency artifact is absent at runtime.
            "binding_required": True,
        }
    if action_name == "knowledge.retrieve_current":
        return {
            "query": {
                "schema_version": 1,
                "subject_semantic_signatures": [{"schema_version": 1, "object_type": "organization"}],
                "goal_semantic_signature": {
                    "schema_version": 1,
                    "objective_key": "observe_contacts",
                    "kpis": [],
                },
            }
        }
    if action_name == "decision.recommend_next_action":
        if "review_business_income" in intent.requested_outcomes:
            return {
                "goal": intent.objective[:1000],
                "options": [],
                "criteria": [],
                "evidence": [],
                "constraints": [
                    "Use only approved business profile facts.",
                    "Do not invent revenue, costs, demand, or customer results.",
                    "Do not execute external actions.",
                ],
                "context": {
                    "review_kind": "business_income",
                    "binding_required": True,
                    "binding_source": "upstream_business_profile_facts",
                },
            }
        return {
            "goal": (intent.objective or "Recommend next research or outreach step")[:1000],
            "options": [
                {
                    "option_id": "await_observed_contacts",
                    "label": "Wait for observed contacts",
                    "description": "Do not invent emails or phones.",
                }
            ],
            "criteria": [
                {
                    "criterion_id": "has_real_contact",
                    "label": "Real observed contact",
                    "weight": 1.0,
                    "required": True,
                }
            ],
            "evidence": [],
            "constraints": ["Do not invent contact emails or phone numbers"],
            "context": {
                "binding_source": "upstream_observed_contacts",
                "binding_required": False,
            },
        }
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
                "source": "internal_crm" if _ajenda_internal_crm_only(intent) else "local_fixture",
            },
        }
    if action_name == "research.verify_public_identity":
        primary = intent.target_entities[0] if intent.target_entities else None
        attrs = primary.attributes if primary and isinstance(primary.attributes, dict) else {}
        candidate_url = str(attrs.get("url") or attrs.get("website") or attrs.get("domain") or "").strip()
        if not candidate_url:
            match = re.search(r"https?://[^\s<>()]+", _instruction_text(intent), flags=re.IGNORECASE)
            candidate_url = match.group(0) if match else ""
        if candidate_url and "://" not in candidate_url:
            candidate_url = f"https://{candidate_url.lstrip('.')}"
        expected_company = str(attrs.get("expected_company") or attrs.get("company") or attrs.get("name") or "").strip()
        industry = str(attrs.get("industry") or "").strip()
        location = str(attrs.get("location") or "").strip()
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
            follow_match = re.search(
                r"\bfollow\b[^.!?]{0,100}\blink\b",
                source,
                flags=re.IGNORECASE,
            )
            quoted_link = re.search(r"[\"“](.+?)[\"”]", source)
            if follow_match and quoted_link:
                link_text = quoted_link.group(1).strip().rstrip("…").rstrip(".").strip()
                if link_text:
                    # Match a stable text prefix across typographic/ASCII punctuation.
                    commands.append({"action": "click", "selector": f'a:text-is("{link_text}")'})
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
    if action_name in {"sales.research", "crm.research"}:
        # Explicit HubSpot / CRM read jobs must fail closed on external errors —
        # never silently complete with Ajenda-brain internal records.
        require_external = "read_crm" in {str(o) for o in intent.requested_outcomes} or "hubspot_source" in {
            str(item) for item in intent.context_requirements
        }
        if require_external:
            crm_source = _source_instruction(intent).lower()
            # sales.research only searches by company/domain — reject scopes the adapter drops.
            unsupported_scope = False
            if re.search(r"\bdeals?\b|\bpipeline\b", crm_source) and not explicit_company:
                unsupported_scope = True
            if re.search(
                r"\b(?:modified|updated|changed)\b.{0,32}\b(?:last|past)\s+\d+\s+days?\b",
                crm_source,
            ):
                unsupported_scope = True
            if re.search(r"\blist\b.{0,24}\bcontacts?\b", crm_source) and not explicit_company:
                unsupported_scope = True
            # The current HubSpot adapter accepts company/domain lookup only.
            # Market, location, quantity, and competitor discovery cannot be
            # represented faithfully without inventing a company search term.
            if any(entity.type == "competitor_set" for entity in intent.target_entities):
                unsupported_scope = True
            if not explicit_company and (industry or location or intent.requested_quantity is not None):
                unsupported_scope = True
            if unsupported_scope:
                raise ValueError(
                    "HubSpot request scope (object type / date filter / contact list) cannot be "
                    "expressed by sales.research company search; refusing silent wrong-scope read"
                )
        return {
            "lead": lead,
            "context": {
                "require_external_crm": require_external,
                "crm_source": "hubspot" if require_external else "auto",
                "objective": intent.objective[:300],
            },
        }
    if action_name in {"sales.qualify", "sales.score_lead", "sales.recommend_next_action"}:
        local_fixture_only = _local_fixture_only(intent)
        qualification_quantity = intent.qualification_quantity or limit
        ranking_only = is_ranking_only_instruction(intent.objective)
        qualification_threshold = (
            5
            if local_fixture_only
            or intent.qualification_quantity is not None
            or "observe_contacts" in intent.requested_outcomes
            else 7
        )
        return {
            "lead": lead,
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_prospect_candidates",
                "requested_quantity": qualification_quantity,
                "mission_specific_scoring": True,
                "qualification_threshold_10": qualification_threshold,
                "ranking_only": ranking_only,
            },
        }
    if action_name == "gtm.lead_enrich":
        return {
            "company": company_label,
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_qualified_prospects",
            },
        }
    if action_name == "gtm.email_draft":
        topic = f"Introduction — {industry}" if industry else "Introduction"
        if location:
            topic = f"{topic} ({location})"
        explicit = _explicit_email(intent)
        recipient = explicit or "pending.binding@invalid.local"
        if explicit:
            compose_note = "Recipient taken from explicit address in the mission instruction."
            binding_required = False
            binding_source = "explicit_recipient"
        else:
            compose_note = (
                "Recipient stays non-deliverable until enrich yields a real contact email. "
                "Draft content must still use bound prospect company/signals."
            )
            binding_required = True
            binding_source = "upstream_enriched_prospects"
        return {
            "recipient": recipient,
            "topic": topic[:240],
            "tone": "professional",
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": binding_required,
                "binding_source": binding_source,
                "binding_path": "$.enriched_prospects" if binding_required else None,
                "compose_note": compose_note,
            },
        }
    if action_name == "sales.draft_followup":
        explicit = _explicit_email(intent)
        recipient_name = explicit or "Prospect (pending enrichment)"
        return {
            "recipient_name": recipient_name,
            "topic": f"Follow-up regarding {industry or 'our conversation'}",
            "tone": "professional",
            "context": {
                "company": company_label,
                "location": location,
                "binding_required": explicit is None,
                "binding_source": "explicit_recipient" if explicit else "upstream_enriched_prospects",
            },
        }
    if action_name == "gtm.email_send":
        explicit = _explicit_email(intent)
        return {
            "to": explicit or "pending.binding@invalid.local",
            "subject": f"Introduction — {industry or 'Ajenda'}",
            "body": "Prepared by mission composition; requires bound recipient and human review before send.",
            "context": {
                "objective": intent.objective[:300],
                "binding_required": explicit is None,
                "binding_source": "explicit_recipient" if explicit else "upstream_enriched_prospects",
                "binding_path": None if explicit else "$.enriched_prospects[*].email",
                "send_policy": intent.send_policy.model_dump(mode="json"),
            },
        }
    if action_name == "gtm.email_check":
        return {"query": _gmail_query(intent), "limit": max(limit, 10)}
    if action_name == "salesforce.soql_read":
        return {"soql": _salesforce_soql(intent), "api_version": "v59.0"}
    if action_name == "gtm.crm_upsert":
        # Market labels must not become static contacts; bind discovered prospects.

        named = None
        for entity in intent.target_entities:
            if entity.name and entity.type in {"company", "person", "contact"}:
                named = entity.name
                break
        return {
            "record_type": "contact",
            "data": {
                "company": named or "pending.binding.company",
                "industry": industry,
                "location": location,
            },
            "context": {
                "source": "mission_composition",
                "binding_required": named is None,
                "binding_source": "explicit_company" if named else "upstream_prospect_candidates",
                "binding_path": None if named else "$.prospect_candidates",
                "compose_note": (
                    "CRM write uses the named company from the instruction."
                    if named
                    else (
                        "CRM write must bind discovered/qualified prospect records — "
                        "refusing to upsert the market label alone."
                    )
                ),
            },
        }
    if action_name == "retrieval.hybrid_search" and (
        "read_business_profile" in intent.requested_outcomes or "review_business_income" in intent.requested_outcomes
    ):
        return {
            "query": "Ajenda products services target customers differentiators approved business profile",
            "limit": min(max(limit, 5), 20),
        }
    if action_name == "record.search":
        return {
            "record_type": "account",
            # Internal CRM missions request a bounded record set. Matching the
            # full natural-language instruction against stored record text can
            # hide every valid account before qualification starts.
            "query": ""
            if "internal_crm_source" in intent.context_requirements
            else _compact_research_query(intent)[:240],
            "limit": limit,
        }
    if action_name in {"document.search", "retrieval.hybrid_search"}:
        return {"query": query, "limit": limit}
    if action_name == "gtm.social_publish":
        # Build a schema-valid publish payload; never leave content empty.
        objective = (intent.objective or "").strip()
        lower_obj = objective.lower()
        platform = "linkedin"
        if "twitter" in lower_obj or re.search(r"\bx\b", lower_obj):
            platform = "twitter"
        elif "facebook" in lower_obj:
            platform = "facebook"
        result_based = any(
            isinstance(entity.attributes, dict) and entity.attributes.get("publish_result_based")
            for entity in intent.target_entities
        ) or bool(re.search(r"\b(?:post|publish|share)\s+(?:the\s+)?(?:results?|findings?|them)\b", lower_obj))
        if result_based:
            # Do not publish the mission command text; bind upstream research outputs.
            content = "Pending research results for social publish (bind after upstream research)."
            return {
                "platform": platform,
                "content": content[:280],
                "context": {
                    "objective": objective[:300],
                    "source": "mission_composition",
                    "binding_required": True,
                    "binding_source": "upstream_prospect_candidates",
                    "binding_path": "$.prospect_candidates",
                    "compose_note": (
                        "Result-based publish must bind research outputs; "
                        "refusing to post the raw instruction as content."
                    ),
                },
            }
        content = objective[:280] if objective else "Ajenda composed social update"
        if len(content) < 1:
            content = "Ajenda composed social update"
        return {
            "platform": platform,
            "content": content,
            "context": {
                "objective": objective[:300],
                "source": "mission_composition",
                "binding_required": False,
                "binding_source": "standalone_publish_content",
            },
        }
    if action_name == "google_calendar.events_read":
        start, end = _calendar_window_from_objective(
            intent.raw_instruction or intent.normalized_instruction or intent.objective
        )
        payload: dict[str, Any] = {"calendar_id": "primary", "limit": max(limit, 20)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        return payload
    if action_name == "calendar.read":
        start, end = _calendar_window_from_objective(intent.objective)
        payload = {"limit": max(limit, 20)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        return payload
    if action_name == "sales.log_activity":
        return {
            "record_type": "activity",
            "data": {
                "lead": lead,
                "type": "note",
                "summary": intent.objective[:240],
            },
        }
    if action_name == "record.write":
        role = (vertical_role or "").strip().lower()
        workflow_context = (
            "gtm"
            if role in {"vertical.gtm", "vertical.sales", "vertical.email"}
            else ("vertical" if role.startswith("vertical.") else "crm")
        )
        return {
            "record_type": "contact",
            "data": {},
            "context": {
                "source": "mission_composition",
                "binding_required": True,
                "prospect_candidates": [],
                "qualified_prospects": [],
                "observed_contacts": [],
                "workflow_context": workflow_context,
            },
        }
    if action_name in {"vertical.finance.prepare_reconciliation", "vertical.finance.prepare_invoice_drafts"}:
        return {
            "revenue_records": [],
            "context": {"binding_required": True, "binding_source": "upstream_revenue_records"},
        }

    if action_name == "linkedin.profile_read":
        # Optional profile_id from target entity attributes or name; default = authenticated user.
        profile_id = None
        for entity in intent.target_entities:
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            if attrs.get("linkedin_profile_id"):
                profile_id = str(attrs["linkedin_profile_id"])
                break
            if entity.type in {"person", "linkedin_profile"} and entity.name:
                profile_id = entity.name
                break
        payload = {
            "fields": ("id", "firstName", "lastName", "headline"),
        }
        if profile_id:
            payload["profile_id"] = profile_id
        return payload
    if action_name == "github.repo_read":
        parsed = extract_github_owner_repo(intent)
        if parsed is None:
            raise ValueError(
                "github.repo_read requires owner and repository (for example octocat/Hello-World); "
                "refusing to invent a placeholder repository"
            )
        owner, repo = parsed
        return {"owner": owner, "repo": repo}
    if action_name == "provider.external_read":
        # Contacts-shaped default when composition selected this action for ops.google_contacts_read.
        # Generic external read still accepts an explicit URL via target entity attributes.
        explicit_url = None
        for entity in intent.target_entities:
            if entity.url:
                explicit_url = entity.url
                break
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            if attrs.get("provider_read_url"):
                explicit_url = str(attrs["provider_read_url"])
                break
        if explicit_url:
            return {
                "method": "GET",
                "url": explicit_url,
                "timeout_seconds": 5.0,
                "allowed_hosts": [],
            }
        # Default: Google People API connections list (read-only contacts surface).
        return {
            "method": "GET",
            "url": (
                "https://people.googleapis.com/v1/people/me/connections"
                "?personFields=names,emailAddresses,phoneNumbers&pageSize=25"
            ),
            "timeout_seconds": 5.0,
            "allowed_hosts": ["people.googleapis.com"],
        }

    return {"context": {"objective": intent.objective[:300], "query": query}}
