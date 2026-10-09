"""Shared deterministic parsing helpers for mission-composed action inputs."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from backend.services.mission_composition.contracts import MissionIntent

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
        "internal_crm_source" in intent.context_requirements
        or re.search(
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
