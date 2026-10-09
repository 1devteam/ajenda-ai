"""Public-identity verification action."""

from backend.services.internet.browser_session import run_browser_session
from backend.services.tools.contact_observation import page_host
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    ResearchVerifyPublicIdentityInput,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.tools.web_action_identity_policy import (
    _contains_any_identity_marker,
    _contains_identity_marker,
    _host_identity_tokens,
    _identity_evidence_excerpt,
    _identity_tokens,
    _industry_evidence_markers,
    _is_directory_or_third_party_host,
    _is_directory_or_third_party_page,
)


def research_verify_public_identity(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Verify one official public page against explicit identity expectations."""

    payload = ResearchVerifyPublicIdentityInput.model_validate(invocation.input)
    snapshot = run_browser_session(
        url_or_domain=payload.url,
        timeout_seconds=payload.timeout_seconds,
        allowed_origins=[payload.url],
        observation_requirements=[{"kind": "title"}, {"kind": "body"}],
    )
    observed = " ".join(
        str(item.get("value") or "")
        for item in (snapshot.extraction.get("observation_requirements", []) if snapshot.extraction else [])
        if isinstance(item, dict)
    ).lower()
    title = next(
        (
            str(item.get("value") or "")
            for item in (snapshot.extraction.get("observation_requirements", []) if snapshot.extraction else [])
            if isinstance(item, dict) and item.get("kind") == "title"
        ),
        "",
    )
    host = page_host(snapshot.url)
    company_tokens = _identity_tokens(payload.expected_company)
    host_tokens = _host_identity_tokens(host)
    company_phrase = " ".join(company_tokens)
    company_phrase_match = bool(company_phrase) and _contains_identity_marker(observed, company_phrase)
    host_match = _contains_any_identity_marker(observed, tuple(token for token in host_tokens if len(token) >= 4))
    company_match = company_phrase_match or host_match
    industry_markers = _industry_evidence_markers(payload.industry)
    industry_match = _contains_any_identity_marker(observed, industry_markers)
    location_markers = _identity_tokens(payload.location)
    location_match = _contains_any_identity_marker(observed, location_markers)
    directory = _is_directory_or_third_party_host(host) or _is_directory_or_third_party_page(observed)
    verified = bool(
        snapshot.real and not directory and (company_match or host_match) and industry_match and location_match
    )
    gaps = []
    if not snapshot.real:
        gaps.append(snapshot.error or "page_not_observed")
    if directory:
        gaps.append("directory_or_third_party_page")
    if not (company_match or host_match):
        gaps.append("company_identity_not_matched")
    if not industry_match:
        gaps.append("industry_not_observed")
    if not location_match:
        gaps.append("location_not_observed")
    company_markers = tuple(dict.fromkeys((company_phrase, *host_tokens)))
    identity_match_evidence = [
        {
            "criterion": "company_name_or_domain",
            "matched": company_match or host_match,
            "match_basis": "company_phrase" if company_phrase_match else "official_host_token" if host_match else None,
            "markers": list(company_markers),
            "observed_excerpt": _identity_evidence_excerpt(observed, company_markers),
            "source_url": snapshot.url if snapshot.real else None,
        },
        {
            "criterion": "industry",
            "matched": industry_match,
            "markers": list(_industry_evidence_markers(payload.industry)),
            "observed_excerpt": _identity_evidence_excerpt(observed, industry_markers),
            "source_url": snapshot.url if snapshot.real else None,
        },
        {
            "criterion": "location",
            "matched": location_match,
            "markers": list(location_markers),
            "observed_excerpt": _identity_evidence_excerpt(observed, tuple(location_markers)),
            "source_url": snapshot.url if snapshot.real else None,
        },
    ]
    artifact = {
        "source_url": payload.url,
        "final_url": snapshot.url if snapshot.real else None,
        "title": title or None,
        "expected_company": payload.expected_company,
        "expected_industry": payload.industry,
        "expected_location": payload.location,
        "identity_status": "verified" if verified else "unverified",
        "identity_evidence_urls": [snapshot.url] if verified else [],
        "identity_match_reasons": [
            reason
            for reason, matched in (
                ("company_name_or_domain", company_match or host_match),
                ("industry", industry_match),
                ("location", location_match),
            )
            if matched
        ],
        "identity_match_evidence": identity_match_evidence,
        "identity_gaps": gaps,
        "observation_timestamp": snapshot.extraction.get("observation_timestamp") if snapshot.extraction else None,
        "browser_trace": snapshot.extraction.get("steps", []) if snapshot.extraction else [],
        "blocked_requests": snapshot.extraction.get("blocked_samples", []) if snapshot.extraction else [],
    }
    summary = f"Public identity {'verified' if verified else 'unverified'} for {payload.expected_company}."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.research.verify_public_identity",
        action_name="research.verify_public_identity",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=artifact,
        confidence=0.9 if verified else 0.35,
        limitations=["official page evidence is required", "directory pages are never accepted as company identity"],
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry"},
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="research.verify_public_identity",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output={"public_identity_observation": artifact},
        evidence=[evidence],
        summary=summary,
        confidence=0.9 if verified else 0.35,
    )
