"""Typed user-requested deliverable semantics for mission composition.

This module interprets explicit output-field requests only. It does not select
jobs, grant authority, materialize artifacts, or execute work.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DeliverableFieldKey = Literal[
    "company_name",
    "website",
    "product_description",
    "qualification_evidence",
    "qualification_reasons",
    "qualification_dimensions",
    "disqualifiers",
    "recommended_next_action",
    "ajenda_relevance",
    "qualification_score",
    "research_summary",
    "income_opportunities",
    "supporting_evidence",
    "estimated_business_impact",
    "confidence",
    "missing_information",
    "sources",
    "drafts",
    "assumptions",
    "limitations",
    "source_url",
    "final_url",
    "title",
    "extracted_observations",
    "observation_timestamp",
    "browser_trace",
    "blocked_requests",
    "observation_satisfied",
    "expected_company",
    "expected_industry",
    "expected_location",
    "identity_status",
    "identity_evidence_urls",
    "identity_match_reasons",
    "identity_match_evidence",
    "identity_gaps",
    "revenue_amount",
    "revenue_currency",
    "revenue_source",
    "goal_status",
    "goal_confidence",
    "kpi_evaluations",
    "progress_gaps",
    "evidence_gaps",
    "evaluation_explanations",
]


class DeliverableFieldRequirement(BaseModel):
    """One explicit field the user requires in the final deliverable."""

    model_config = ConfigDict(extra="forbid")

    field_key: DeliverableFieldKey
    source_text: str = Field(min_length=1, max_length=500)
    required: bool = True


class DeliverableRequest(BaseModel):
    """Typed composition-time output contract; never execution authority."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["revops_report"] = "revops_report"
    scope: Literal["per_prospect", "mission"]
    fields: tuple[DeliverableFieldRequirement, ...] = Field(default=(), max_length=30)
    unresolved_items: tuple[str, ...] = Field(default=(), max_length=30)
    score_min: int | None = Field(default=None, ge=0, le=100)
    score_max: int | None = Field(default=None, ge=0, le=100)
    grants_execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_score_range(self) -> DeliverableRequest:
        if (self.score_min is None) != (self.score_max is None):
            raise ValueError("deliverable score range requires both minimum and maximum")
        if self.score_min is not None and self.score_max is not None and self.score_min >= self.score_max:
            raise ValueError("deliverable score minimum must be less than maximum")
        return self

    @property
    def fully_understood(self) -> bool:
        return bool(self.fields) and not self.unresolved_items


_DELIVERABLE_SENTENCE = re.compile(
    r"(?P<prefix>for\s+each\s+(?:prospect|company|lead)[^.!?]{0,80}?\b(?:provide|return|include)\b|"
    r"\b(?:provide|return|include)\b)(?P<body>[^.!?]{1,1600})",
    re.IGNORECASE,
)
_SCORE_RANGE = re.compile(r"\b(?:from\s+)?(?P<minimum>\d{1,2})\s*(?:to|[-\u2013])\s*(?P<maximum>\d{1,2})\b")
_TRAILING_PURPOSE = re.compile(r"\s+for\s+(?:review|approval|the\s+user)\s*$", re.IGNORECASE)

_FIELD_PATTERNS: tuple[tuple[DeliverableFieldKey, tuple[str, ...]], ...] = (
    ("company_name", (r"\bcompany\s+name\b", r"\bprospect\s+name\b")),
    ("expected_company", (r"\bexpected\s+company\b", r"\bcompany\s+being\s+verified\b")),
    ("expected_industry", (r"\bexpected\s+industry\b", r"\bdeclared\s+industry\b")),
    ("expected_location", (r"\bexpected\s+location\b", r"\bdeclared\s+location\b")),
    ("identity_status", (r"\bidentity\s+status\b", r"\bverification\s+status\b")),
    ("identity_evidence_urls", (r"\bidentity\s+evidence\s+(?:urls?|links?)\b", r"\bidentity\s+sources?\b")),
    ("identity_match_reasons", (r"\bidentity\s+match\s+reasons?\b", r"\bidentity\s+evidence\s+reasons?\b")),
    ("identity_match_evidence", (r"\bidentity\s+match\s+evidence\b", r"\bverification\s+evidence\s+details?\b")),
    ("identity_gaps", (r"\bidentity\s+gaps?\b", r"\bverification\s+gaps?\b")),
    ("source_url", (r"\bsource\s+url\b", r"\bsource\s+page\s+url\b")),
    # Browser observation fields must precede the broad prospect ``url`` rule.
    # Otherwise "final URL" is misclassified as a prospect website.
    ("final_url", (r"\bfinal\s+url\b", r"\bredirected\s+url\b")),
    ("title", (r"\bpage\s+title\b", r"\btitle\s+of\s+the\s+page\b", r"^the\s+title$", r"^title$")),
    (
        "extracted_observations",
        (
            r"\bvisible\s+(?:page\s+)?text\b",
            r"\bobserved\s+page\s+content\b",
            r"\bextracted\s+(?:page\s+)?text\b",
            r"\bextracted\s+observations?\b",
            r"\bextracted\s+content\b",
        ),
    ),
    (
        "observation_timestamp",
        (
            r"\bobservation\s+timestamp\b",
            r"\btime(?:stamp)?\s+of\s+observation\b",
            r"\bobserved\s+at\b",
        ),
    ),
    ("browser_trace", (r"\bbrowser\s+(?:step\s+)?trace\b", r"\bnavigation\s+trace\b")),
    (
        "blocked_requests",
        (
            r"\bblocked[- ]requests?\b",
            r"\bblocked\s+request\s+list\b",
            r"\bnetwork\s+blocks?\b",
        ),
    ),
    (
        "observation_satisfied",
        (
            r"\bobservation\s+(?:was\s+)?satisfied\b",
            r"\bwhether\s+the\s+observation\s+(?:was\s+)?satisfied\b",
            r"\bsatisfaction\s+of\s+the\s+observation\b",
        ),
    ),
    ("website", (r"\bwebsite\b", r"\bcompany\s+url\b", r"\burl\b")),
    (
        "product_description",
        (
            r"\bwhat\s+(?:it|the\s+company)\s+sells\b",
            r"\bproduct\s+description\b",
            r"\bdescription\s+of\s+what\s+(?:it|the\s+company)\s+sells\b",
        ),
    ),
    (
        "qualification_evidence",
        (
            r"\bevidence\s+used\s+to\s+qualify\b",
            r"\bqualification\s+evidence\b",
            r"\bevidence\s+for\s+qualification\b",
        ),
    ),
    (
        "qualification_reasons",
        (
            r"\bqualification\s+reasons?\b",
            r"\breasons?\s+for\s+qualification\b",
            r"^reasons?$",
        ),
    ),
    (
        "qualification_dimensions",
        (r"\bqualification\s+dimensions?\b", r"\bscoring\s+dimensions?\b"),
    ),
    ("disqualifiers", (r"\bdisqualifiers?\b", r"\bdisqualification\s+reasons?\b")),
    (
        "recommended_next_action",
        (r"\brecommended\s+next\s+actions?\b", r"\bnext\s+actions?\b"),
    ),
    (
        "ajenda_relevance",
        (
            r"\bwhy\s+ajenda(?:\s+ai)?\s+(?:may\s+be|is|could\s+be)\s+relevant\b",
            r"\bajenda(?:\s+ai)?\s+relevance\b",
            r"\bwhy\s+ajenda(?:\s+ai)?\s+may\s+help\b",
        ),
    ),
    (
        "qualification_score",
        (r"\bqualification\s+scores?\b", r"\bprospect\s+scores?\b", r"\bscored\s+records?\b"),
    ),
    ("research_summary", (r"\bthe\s+research\b", r"\bresearch\s+summary\b", r"^research$")),
    ("income_opportunities", (r"\b(?:income|revenue|business)?\s*opportunities?\b",)),
    ("supporting_evidence", (r"\bsupporting\s+evidence\b", r"\bevidence\s+used\b")),
    (
        "estimated_business_impact",
        (r"\bestimated\s+(?:business\s+)?impact\b", r"\bexpected\s+(?:business\s+)?impact\b"),
    ),
    ("goal_status", (r"\b(?:goal\s+)?evaluation\s+status\b", r"\bgoal\s+status\b", r"\bprogress\s+status\b")),
    ("confidence", (r"\bconfidence\b", r"\bconfidence\s+level\b")),
    ("goal_confidence", (r"\bgoal\s+confidence\b",)),
    ("kpi_evaluations", (r"\bkpi\s+evaluations?\b", r"\bkey\s+performance\s+indicator\s+evaluations?\b")),
    ("progress_gaps", (r"\bprogress\s+gaps?\b",)),
    ("evidence_gaps", (r"\bevidence\s+gaps?\b",)),
    ("evaluation_explanations", (r"\bevaluation\s+explanations?\b", r"\bexplanations?\b")),
    ("missing_information", (r"\bmissing\s+information\b", r"\binformation\s+gaps?\b")),
    ("sources", (r"\bsources?\b", r"\bcitations?\b")),
    ("drafts", (r"\bdrafts?\b", r"\bpersonalized\s+drafts?\b")),
    ("assumptions", (r"\bassumptions?\b",)),
    ("limitations", (r"\blimitations?\b",)),
)


def _field_key(item: str) -> DeliverableFieldKey | None:
    normalized = " ".join(item.strip().lower().split())
    for field_key, patterns in _FIELD_PATTERNS:
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            return field_key
    return None


def _split_requested_items(body: str) -> list[str]:
    cleaned = _TRAILING_PURPOSE.sub("", body.strip(" ,;:"))
    items: list[str] = []
    for part in re.split(r"\s*,\s*|\s+and\s+", cleaned, flags=re.IGNORECASE):
        normalized = re.sub(r"^(?:and|or)\s+", "", part.strip(" ,;:"), flags=re.IGNORECASE)
        if normalized:
            items.append(normalized)
    return items


def extract_deliverable_request(text: str) -> DeliverableRequest | None:
    """Extract an explicit RevOps deliverable list without inventing unsupported fields."""

    match = _DELIVERABLE_SENTENCE.search(text)
    if match is None:
        return None

    prefix = match.group("prefix")
    body = match.group("body")
    scope: Literal["per_prospect", "mission"] = "per_prospect" if "for each" in prefix.lower() else "mission"

    fields: list[DeliverableFieldRequirement] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for item in _split_requested_items(body):
        field_key = _field_key(item)
        if field_key is None:
            unresolved.append(item[:500])
            continue
        if field_key in seen:
            continue
        seen.add(field_key)
        fields.append(DeliverableFieldRequirement(field_key=field_key, source_text=item[:500]))

    # Identity missions commonly shorten the final list to ``evidence URLs``
    # and ``match reasons`` after already naming identity fields.  Resolve
    # those unambiguous aliases only in that identity context; keep them
    # unresolved for general research requests where ``evidence`` could mean
    # a different artifact projection.
    identity_context = bool(
        seen.intersection(
            {
                "expected_company",
                "expected_industry",
                "expected_location",
                "identity_status",
                "identity_gaps",
                "identity_match_evidence",
            }
        )
    )
    if identity_context and unresolved:
        identity_aliases: dict[str, DeliverableFieldKey] = {
            "evidence urls": "identity_evidence_urls",
            "evidence links": "identity_evidence_urls",
            "match reasons": "identity_match_reasons",
        }
        remaining_unresolved: list[str] = []
        for item in unresolved:
            alias_key = identity_aliases.get(" ".join(item.lower().split()))
            if alias_key is None or alias_key in seen:
                remaining_unresolved.append(item)
                continue
            seen.add(alias_key)
            fields.append(DeliverableFieldRequirement(field_key=alias_key, source_text=item[:500]))
        unresolved = remaining_unresolved
        requested_order = {
            " ".join(item.lower().split()): index for index, item in enumerate(_split_requested_items(body))
        }
        fields.sort(
            key=lambda field: requested_order.get(" ".join(field.source_text.lower().split()), len(requested_order))
        )

    # "scored records with ..." names the score and then additional fields in
    # the same clause; preserve both typed requirements instead of letting the
    # first matching phrase hide the score.
    if "qualification_score" not in seen and re.search(r"\bscored\s+records?\b", body, flags=re.IGNORECASE):
        seen.add("qualification_score")
        fields.insert(0, DeliverableFieldRequirement(field_key="qualification_score", source_text="scored records"))

    score_min: int | None = None
    score_max: int | None = None
    if "qualification_score" in seen:
        score_match = _SCORE_RANGE.search(body)
        if score_match is not None:
            score_min = int(score_match.group("minimum"))
            score_max = int(score_match.group("maximum"))

    if not fields and not unresolved:
        return None
    return DeliverableRequest(
        scope=scope,
        fields=tuple(fields),
        unresolved_items=tuple(unresolved),
        score_min=score_min,
        score_max=score_max,
    )
