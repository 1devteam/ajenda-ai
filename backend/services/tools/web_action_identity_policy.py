"""Public identity and observed-contact research handlers."""

import re

# These hosts publish listings, reviews, or lead-generation pages.  A matching
# industry/location title on one of them is evidence about a market, not proof
# of an individual company's identity.  Keep this policy in the observer so
# every public-search provider gets the same identity boundary.
_DIRECTORY_HOST_MARKERS = (
    "directory",
    "angi.com",
    "bestprosintown.com",
    "bestpickreports.com",
    "consumeraffairs.com",
    "forbes.com",
    "homeadvisor.com",
    "hvacinformed.com",
    "houzz.com",
    "thumbtack.com",
    "yelp.",
    "yellowpages",
    "facebook.",
    "linkedin.",
    "instagram.",
    "maps.",
    "angi.",
    "bestpickreports.",
    "downtobid.",
    "ensun.",
    "hvacservice.io",
    "indeed.",
    "myhomepros.",
    "reddit.",
)

_DIRECTORY_PAGE_MARKERS = (
    "contractor database",
    "find and invite",
    "find local pros",
    "join as a pro",
    "jobs, employment",
    "browse contractors",
    "search results",
    "request a quote from",
    "top 10 best",
)

_GENERIC_INDUSTRY_WORDS = {"company", "companies", "contractor", "contractors", "services", "service"}

# A ranked/category label is a discovery clue, not a company identity.  Keep
# this structural check independent of the host denylist: unknown directory
# hosts are common in public search results.
_GENERIC_MARKET_LISTING_LABEL = re.compile(
    r"\b(?:\d+\s+)?(?:top|best|leading)\s+(?:\d+\s+)?(?:\.?[a-z0-9&+/'-]+\s+){0,8}"
    r"(?:companies|firms|agencies|providers|contractors|developers)\b",
    flags=re.IGNORECASE,
)

# A category title may omit ranking language altogether (for example,
# ``Software Development Companies in Austin (2026)``).  It is still a market
# listing, rather than a business identity.  This stays structural rather than
# host-specific: newly encountered directories and editorial roundups must not
# become verified companies merely because they are not on a denylist.
_GENERIC_MARKET_CATEGORY_WITH_LOCATION = re.compile(
    r"^\s*(?:\d+\s+)?(?:\.?[a-z0-9&+/'-]+\s+){0,8}"
    r"(?:company|companies|firm|firms|agency|agencies|provider|providers|"
    r"contractor|contractors|developer|developers)\s+"
    r"(?:in|near|around|of|for)\s+[a-z0-9][a-z0-9 .,'&+/'-]{1,80}",
    flags=re.IGNORECASE,
)


def _industry_evidence_markers(industry: object) -> tuple[str, ...]:
    """Return bounded page markers for the declared mission industry."""

    raw = str(industry or "").lower()
    markers = {token for token in re.findall(r"[a-z0-9]+", raw) if len(token) >= 4}
    markers.difference_update(_GENERIC_INDUSTRY_WORDS)
    if "roof" in raw or "roofing" in raw:
        markers.update({"roof", "roofing"})
    if "hvac" in raw or "heating" in raw or "cooling" in raw:
        markers.update({"hvac", "heating", "cooling", "air conditioning", "furnace"})
    return tuple(sorted(markers, key=lambda item: (-len(item), item)))


def _is_directory_or_third_party_host(host: str) -> bool:
    normalized = host.lower().removeprefix("www.").rstrip(".")
    return (
        normalized == "goodfirms.co"
        or normalized.endswith(".goodfirms.co")
        or any(marker in normalized for marker in _DIRECTORY_HOST_MARKERS)
    )


def _is_directory_or_third_party_page(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower())
    return any(marker in normalized for marker in _DIRECTORY_PAGE_MARKERS)


def _is_generic_market_listing_label(value: str) -> bool:
    """Whether a title/label names a ranked market category, not a company."""

    normalized = re.sub(r"\s+", " ", value).strip()
    return bool(
        _GENERIC_MARKET_LISTING_LABEL.search(normalized) or _GENERIC_MARKET_CATEGORY_WITH_LOCATION.search(normalized)
    )


def _brand_from_singular_market_title(*, title: str, host: str) -> str | None:
    """Find a title brand matching the host label for independent verification."""

    parts = re.split(r"\s+[-\u2013\u2014|]\s+", title.strip())
    if len(parts) != 2:
        return None
    host_label = re.sub(r"[^a-z0-9]", "", host.casefold().removeprefix("www.").split(".", 1)[0])
    if len(host_label) < 4:
        return None
    for brand, description in (parts, parts[::-1]):
        if (
            _GENERIC_MARKET_CATEGORY_WITH_LOCATION.match(description)
            and not _GENERIC_MARKET_LISTING_LABEL.search(description)
            and re.search(
                r"\b(?:company|firm|agency|provider|contractor|developer)\s+(?:in|near|around|of|for)\b",
                description,
                re.IGNORECASE,
            )
            and re.sub(r"[^a-z0-9]", "", brand.casefold()) == host_label
        ):
            return brand
    return None


def _operating_locations(page_text: str) -> set[str]:
    """Read explicitly stated operating cities out of visible page text."""

    return {
        re.sub(r"\s+", " ", match.group(1)).casefold()
        for match in re.finditer(
            r"\b(?i:based in|headquartered in|located in|offices? (?:is |are )?in)\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
            page_text,
        )
    }


def _is_plural_market_listing(value: str) -> bool:
    """A category title cannot establish identity even when it names its publisher."""
    title = re.split(r"\s+[-\u2013\u2014|]\s+", value, maxsplit=1)[0]
    return bool(
        _GENERIC_MARKET_LISTING_LABEL.search(title)
        or (
            _GENERIC_MARKET_CATEGORY_WITH_LOCATION.match(title)
            and re.search(
                r"\b(?:companies|firms|agencies|providers|contractors|developers)\s+(?:in|near|around|of|for)\b",
                title,
                re.I,
            )
        )
    )


def _observed_company_brand(*, host: str, label: str, title: str, visible_text: str) -> str | None:
    """Corroborate a company name with the page and its site label."""
    host_label = re.sub(r"[^a-z0-9]", "", host.split(".", 1)[0].casefold())
    for name in (label, *re.split(r"\s+[-\u2013\u2014|]\s+", title)):
        name = name.strip()
        compact = re.sub(r"[^a-z0-9]", "", name.casefold())
        if (
            len(compact) >= 4
            and not _is_generic_market_listing_label(name)
            and _contains_identity_marker(visible_text, name)
            and (compact == host_label or (name == title and _contains_identity_marker(host.replace("-", " "), name)))
        ):
            return name[:160]

    # Search and page titles can omit a brand, or abbreviate it as "BHW".
    # Require a word-delimited name on the observed page whose compact form
    # corroborates the actual host, e.g. "The BHW Group" / thebhwgroup.com.
    if len(host_label) < 4 or len(host_label) > 63:
        return None
    spelling = r"[ -]?".join(re.escape(char) for char in host_label)
    match = re.search(rf"(?<![\w.]){spelling}(?![\w.])", visible_text, flags=re.IGNORECASE)
    return match.group() if match else None


def _operating_location_excerpt(page_text: str, city: str, company: str) -> str | None:
    """Recognize a company-attributed operating location in visible text."""
    city_pattern = r"\s+".join(re.escape(word) for word in city.split())
    brand = re.escape(company)
    subject = rf"(?:{brand}(?:\s+is)?|we are|we(?:'|\u2019)re|our (?:corporate )?(?:office|headquarters) (?:is|are))"
    description = r"(?:\s+(?:a|an|the)\s+[^.!?;]{1,100}?\s+(?:company|team|firm|agency|studio|business))?"
    location = r"(?:based in|headquartered in|located in)"
    match = re.search(
        rf"(?<![\w])(?:{subject}{description}\s+{location}|(?:our )?(?:offices?|headquarters)\s+(?:(?:is|are)\s+)?in)"
        rf"\s+{city_pattern}(?![\w-])",
        page_text,
        flags=re.IGNORECASE,
    )
    return match.group() if match else None


def _market_industry_markers(industry: str) -> tuple[str, ...]:
    if "software development" in industry.casefold():
        return (
            "software development",
            "develops software",
            "builds custom software",
            "app development",
            "application development",
            "web development",
            "mobile development",
        )
    return _industry_evidence_markers(industry)


def _is_source_publisher_family_link(source_host: str, linked_host: str) -> bool:
    """Whether a purported external company link returns to the source publisher.

    Market articles commonly link their own masthead, platform, or parent
    domain alongside companies they mention.  A source such as
    ``builtinaustin.example`` linking to ``builtin.example`` is not independent
    company evidence.  Use a host-label relationship instead of a publisher
    denylist so the boundary applies to previously unseen editorial sites too.
    """

    def _root(host: str) -> str:
        label = host.lower().removeprefix("www.").split(".", 1)[0]
        return re.sub(r"[^a-z0-9]", "", label)

    source_root = _root(source_host)
    linked_root = _root(linked_host)
    if not source_root or not linked_root:
        return False
    shorter, longer = sorted((source_root, linked_root), key=len)
    # Three-letter labels are too collision-prone to establish publisher
    # affinity; four characters retains ordinary brand labels without treating
    # incidental short strings as the same organization.
    return len(shorter) >= 4 and shorter in longer


def _identity_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{3,}", value.lower().replace("'", ""))
        if token not in {"the", "and", "inc", "llc", "company", "companies", "services", "service"}
    ]


def _host_identity_tokens(host: str) -> list[str]:
    label = host.lower().removeprefix("www.").split(".", 1)[0]
    tokens = re.findall(r"[a-z0-9]{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", label))
    if len(label) >= 4:
        # Three-letter prefixes create accidental matches (for example,
        # ``ian`` inside unrelated words). Keep only meaningful host labels.
        tokens.extend(label[:size] for size in (4, 5, 6) if len(label) >= size)
    return [
        token
        for token in tokens
        if token not in {"company", "companies", "heating", "cooling", "plumbing", "services", "service"}
    ]


def _contains_identity_marker(observed: str, marker: str) -> bool:
    """Match a criterion as a word/phrase, not an arbitrary substring."""

    escaped = re.escape(marker.lower().strip())
    if marker.lower().strip() == "global":
        escaped = r"global(?:ly)?"
    return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", observed.lower()) is not None


def _contains_any_identity_marker(observed: str, markers: tuple[str, ...] | list[str]) -> bool:
    return any(_contains_identity_marker(observed, marker) for marker in markers if marker)


def _identity_evidence_excerpt(observed: str, markers: tuple[str, ...], *, limit: int = 280) -> str | None:
    """Return bounded observed text around a matched marker, never an inferred claim."""

    normalized = re.sub(r"\s+", " ", observed).strip()
    for marker in markers:
        pattern = re.escape(marker.lower().strip())
        if marker.lower().strip() == "global":
            pattern = r"global(?:ly)?"
        match = re.search(
            rf"(?<![a-z0-9]){pattern}(?![a-z0-9])",
            normalized.lower(),
        )
        if match is None:
            continue
        start = max(0, match.start() - 80)
        return normalized[start : start + limit]
    return None
