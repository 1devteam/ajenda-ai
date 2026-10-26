"""Pure, canonical subject identity across historical need and typed ontology records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.services.ontology.types import BusinessObjectRef


def canonical_subject_keys(subjects: Sequence[BusinessObjectRef | dict[str, Any]]) -> frozenset[tuple[str, str]]:
    """Compare source-owned subject identities across canonical and historical need records.

    Historical BusinessNeedRevision records use {"kind", "id"}; typed
    measurement/goal references use {"object_type", "object_id"}. Only these
    two exact schemas are accepted. Never infer an identity from display text.
    """

    canonical: set[tuple[str, str]] = set()
    for item in subjects:
        if isinstance(item, dict) and set(item) == {"kind", "id"}:
            item = {"object_type": item["kind"], "object_id": item["id"]}
        reference = item if isinstance(item, BusinessObjectRef) else BusinessObjectRef.model_validate(item)
        canonical.add((reference.object_type.value, reference.object_id))
    return frozenset(canonical)


