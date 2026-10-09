"""Public identity and observed-contact research handlers."""

from __future__ import annotations

import re

from datetime import (
    UTC,
    datetime,
)

from backend.services.internet import fetch_public_page

from backend.services.internet.browser_session import run_browser_session

from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)

from backend.services.tools.action_registry import ActionRegistry

from backend.services.tools.contact_observation import (
    extract_observed_contacts,
    page_host,
    prospect_source_url,
)

from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    ResearchObserveContactsInput,
    ResearchVerifyPublicIdentityInput,
    SideEffectClass,
    ToolInvocation,
)

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
    return any(marker in normalized for marker in _DIRECTORY_HOST_MARKERS)

def _is_directory_or_third_party_page(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower())
    return any(marker in normalized for marker in _DIRECTORY_PAGE_MARKERS)

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
