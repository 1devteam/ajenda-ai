from __future__ import annotations

import re
from enum import StrEnum


class ComplianceCategory(StrEnum):
    OPERATIONAL = "operational"
    CONSUMER_INTERACTION = "consumer_interaction"
    MARKETING = "marketing"
    EMPLOYMENT = "employment"
    FINANCIAL = "financial"
    HEALTHCARE = "healthcare"
    PUBLIC_CONTENT = "public_content"


class ComplianceJurisdiction(StrEnum):
    US_ALL = "US-ALL"
    US_CO = "US-CO"
    US_NY = "US-NY"
    GLOBAL = "global"


ALLOWED_COMPLIANCE_CATEGORIES: frozenset[str] = frozenset(category.value for category in ComplianceCategory)
CANONICAL_EXPLICIT_JURISDICTIONS: frozenset[str] = frozenset(
    jurisdiction.value for jurisdiction in ComplianceJurisdiction
)
_US_STATE_JURISDICTION_RE = re.compile(r"^US-[A-Z]{2}$")
_EU_JURISDICTION_RE = re.compile(r"^EU(?:-[A-Z]{2})?$")


def is_supported_compliance_category(value: str) -> bool:
    return value in ALLOWED_COMPLIANCE_CATEGORIES


def is_supported_jurisdiction(value: str) -> bool:
    return (
        value in CANONICAL_EXPLICIT_JURISDICTIONS
        or _US_STATE_JURISDICTION_RE.fullmatch(value) is not None
        or _EU_JURISDICTION_RE.fullmatch(value) is not None
    )
