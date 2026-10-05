"""Canonical proposal/application bindings for tenant business knowledge.

Bindings are integrity metadata, not authorization.  They make the exact
proposal and exact fact written to a profile inspectable and tamper-evident
across the review boundary.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion

PROPOSAL_BINDING_VERSION = 1
_BINDING_KEY = "_proposal_binding"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _proposal_payload(suggestion: BusinessProfileSuggestion, *, binding_id: str) -> dict[str, Any]:
    source_context = dict(suggestion.source_context or {})
    source_context.pop(_BINDING_KEY, None)
    return {
        "binding_id": binding_id,
        "tenant_id": suggestion.tenant_id,
        "suggested_category": suggestion.suggested_category,
        "suggested_fact": suggestion.suggested_fact,
        "rationale": suggestion.rationale,
        "source_context": source_context,
    }


def ensure_proposal_binding(suggestion: BusinessProfileSuggestion) -> dict[str, Any]:
    """Attach or verify a server-generated immutable proposal fingerprint."""
    source_context = dict(suggestion.source_context or {})
    existing = source_context.get(_BINDING_KEY)
    binding_id = (
        str(existing.get("binding_id"))
        if isinstance(existing, dict) and existing.get("binding_id")
        else str(uuid.uuid4())
    )
    payload = _proposal_payload(suggestion, binding_id=binding_id)
    expected = {"version": PROPOSAL_BINDING_VERSION, "binding_id": binding_id, "proposal_digest": _digest(payload)}
    if isinstance(existing, dict) and existing.get("proposal_digest") not in (None, expected["proposal_digest"]):
        raise ValueError("business profile proposal binding is invalid")
    source_context[_BINDING_KEY] = expected
    suggestion.source_context = source_context
    return expected


def build_application_binding(
    *,
    suggestion: BusinessProfileSuggestion,
    profile: BusinessProfile,
    approved_fact: dict[str, object],
    previous_fact: Any,
    previous_provenance: Any,
    decision: str,
) -> dict[str, Any]:
    proposal_binding = ensure_proposal_binding(suggestion)
    approved_fact_digest = _digest(approved_fact)
    previous_fact_digest = _digest(previous_fact)
    previous_provenance_digest = _digest(previous_provenance)
    application_payload = {
        "version": PROPOSAL_BINDING_VERSION,
        "proposal_digest": proposal_binding["proposal_digest"],
        "tenant_id": suggestion.tenant_id,
        "profile_id": str(profile.id) if profile.id is not None else None,
        "category": suggestion.suggested_category,
        "approved_fact_digest": approved_fact_digest,
        "previous_fact_digest": previous_fact_digest,
        "previous_provenance_digest": previous_provenance_digest,
        "decision": decision,
    }
    return {
        **application_payload,
        "application_digest": _digest(application_payload),
    }
