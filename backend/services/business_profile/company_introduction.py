"""Build a review-only company introduction from approved profile facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.business_profile.categories import profile_category_for_field

MemoryLookupStatus = Literal["matched", "no_matches", "unavailable"]


class CompanyIntroductionDraft(BaseModel):
    """One durable text draft with a scope and an explicit evidence boundary."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    body: str = Field(min_length=1)
    source_fields: tuple[str, ...] = Field(min_length=1)
    memory_reference_ids: tuple[str, ...] = ()
    memory_lookup_status: MemoryLookupStatus | None = None


def build_company_introduction(
    profile_brief: dict[str, object],
    *,
    memory_reference_ids: tuple[str, ...],
    memory_lookup_status: MemoryLookupStatus | None = None,
) -> CompanyIntroductionDraft:
    """Format approved facts without adopting unreviewed memory as profile truth."""

    facts = profile_brief.get("facts")
    conflicts = profile_brief.get("conflicting_fields")
    if not isinstance(facts, dict) or not isinstance(conflicts, list):
        raise ValueError("Company introduction requires a valid approved profile brief.")
    fields: list[str] = []
    sections: list[str] = []
    for field, lead in (
        ("business_name", None),
        ("description", None),
        ("products_services", "Products and services include"),
        ("target_customers", "We serve"),
        ("differentiators", "Our differentiators include"),
    ):
        if field in conflicts or profile_category_for_field(field) in conflicts:
            continue
        value = facts.get(field)
        if isinstance(value, list):
            value = ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
        if not isinstance(value, str) or not value.strip():
            continue
        fields.append(field)
        sections.append(f"{lead} {value.strip().rstrip('.')}." if lead else value.strip())
    if "business_name" not in fields or len(fields) < 2:
        raise ValueError(
            "Company introduction requires an unconflicted business name and at least one descriptive fact."
        )
    return CompanyIntroductionDraft(
        body="\n\n".join(sections),
        source_fields=tuple(fields),
        memory_reference_ids=memory_reference_ids,
        memory_lookup_status=memory_lookup_status,
    )
