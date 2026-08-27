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
    "ajenda_relevance",
    "qualification_score",
    "research_summary",
    "sources",
    "drafts",
    "assumptions",
    "limitations",
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
        (r"\bqualification\s+reasons?\b", r"\breasons?\s+for\s+qualification\b"),
    ),
    (
        "ajenda_relevance",
        (
            r"\bwhy\s+ajenda(?:\s+ai)?\s+(?:may\s+be|is|could\s+be)\s+relevant\b",
            r"\bajenda(?:\s+ai)?\s+relevance\b",
            r"\bwhy\s+ajenda(?:\s+ai)?\s+may\s+help\b",
        ),
    ),
    ("qualification_score", (r"\bqualification\s+score\b", r"\bprospect\s+score\b")),
    ("research_summary", (r"\bthe\s+research\b", r"\bresearch\s+summary\b", r"^research$")),
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
