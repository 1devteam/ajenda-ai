"""Deterministic plain-language → MissionIntent interpreter.

Emits canonical outcome IDs, structured quantity / send policy, and restatement
requirements. Does not select actions, grant credentials, or queue work.

Each compose submit is a standalone raw instruction — no client fragment merge.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.ability_vocab import match_outcome_phrases
from backend.services.mission_composition.connector_capabilities import restatement_for_deferred_op
from backend.services.mission_composition.contracts import (
    CANONICAL_OUTCOMES,
    INTERPRETER_VERSION,
    CanonicalOutcome,
    Clarification,
    Contradiction,
    InterpretationEvidence,
    InterpretedClause,
    MissionIntent,
    SendPolicy,
    SuccessCriterion,
    TargetEntity,
)
from backend.services.mission_composition.interpretation.fuzzy import fuzzy_outcome_candidates
from backend.services.mission_composition.interpretation.lexical import classify_lexical_frame
from backend.services.mission_composition.interpretation.normalize import normalize_instruction_text
from backend.services.mission_composition.interpretation.rule_engine import (
    _BUSINESS_PROFILE_CONTEXT_PATTERNS,
    _BUSINESS_PROFILE_READ_PATTERNS,
    _CALENDAR_MUTATION_PATTERNS,
    _CALENDAR_PATTERNS,
    _COMPONENTS_ACTIVE,
    _CONDITIONAL_SEND_PATTERNS,
    _CONTACTS_READ_PATTERNS,
    _CRM_NEGATION_PATTERNS,
    _CRM_READBACK_VERIFICATION_PATTERN,
    _CRM_READ_NEGATION_PATTERNS,
    _CRM_READ_PATTERNS,
    _CRM_UPDATE_PATTERNS,
    _DIRECT_CRM_RECORD_READ,
    _DRAFT_PATTERNS,
    _EMAIL_READ_PATTERNS,
    _ENRICH_PATTERNS,
    _GITHUB_READ_PATTERNS,
    _INTERNAL_CRM_PATTERNS,
    _INTERNAL_CRM_READ_NEGATION_PATTERNS,
    _INTERNAL_CRM_READ_PATTERNS,
    _LINKEDIN_READ_PATTERNS,
    _NO_EXTERNAL_ACTION_PATTERNS,
    _NO_SEND_PATTERNS,
    _OBSERVE_CONTACT_PATTERNS,
    _PUBLISH_NEGATION_PATTERNS,
    _PUBLISH_PATTERNS,
    _PUBLISH_RESULT_BASED,
    _QUALIFY_PATTERNS,
    _REPORT_SYNTHESIS_REQUEST,
    _RESEARCH_PATTERNS,
    _SALESFORCE_QUERY_PATTERNS,
    _SEND_CONTRADICTION_PATTERNS,
    _classify_clause as _classify_clause_impl,
    _contains_any,
    _contains_unnegated_send,
    _evidence,
    _extract_connector_company,
    _extract_count,
    _extract_qualification_count,
    _extract_target_entities,
    _looks_like_fragment,
    _restatement,
    _segment_clauses as _segment_clauses_impl,
    _success_for_outcomes,
)


def _segment_clauses(text: str, *, protected_spans: list[str] | None = None) -> list[str]:
    """Compatibility boundary for the canonical graph-visible clause segmenter."""

    return _segment_clauses_impl(text, protected_spans=protected_spans)


def _classify_clause(
    clause: str,
    *,
    profile_mission: bool = False,
    external_action_forbidden: bool = False,
    business_income_review: bool = False,
    goal_progress_evaluation: bool = False,
) -> tuple[list[CanonicalOutcome], bool, bool]:
    """Compatibility boundary for the canonical graph-visible clause classifier."""

    return _classify_clause_impl(
        clause,
        profile_mission=profile_mission,
        external_action_forbidden=external_action_forbidden,
        business_income_review=business_income_review,
        goal_progress_evaluation=goal_progress_evaluation,
    )


def interpret_instruction(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
    spelling_enabled: bool | None = None,
    fuzzy_enabled: bool | None = None,
) -> MissionIntent:
    """Extract a candidate MissionIntent without granting execution authority."""

    raw_instruction = instruction
    text = instruction.strip()
    if not text:
        raise ValueError("instruction must be non-empty")

    # Settings are optional so unit tests stay free of full app config.
    if spelling_enabled is None or fuzzy_enabled is None:
        try:
            from backend.app.config import get_settings

            settings = get_settings()
            if spelling_enabled is None:
                spelling_enabled = bool(settings.mission_interpreter_spelling_enabled)
            if fuzzy_enabled is None:
                fuzzy_enabled = bool(settings.mission_interpreter_fuzzy_enabled)
        except Exception:
            spelling_enabled = True if spelling_enabled is None else spelling_enabled
            fuzzy_enabled = True if fuzzy_enabled is None else fuzzy_enabled

    norm = normalize_instruction_text(text, spelling_enabled=bool(spelling_enabled))
    text = norm.normalized
    components_active: list[str] = list(dict.fromkeys([*_COMPONENTS_ACTIVE, *norm.components_active]))

    profile_context = profile_context or {}
    lower = text.lower()
    lexical_frame = classify_lexical_frame(text)
    components_active.append("structured_lexical_frame")
    legacy_business_income_review = re.search(
        r"\breview\s+my\s+business\b.{0,120}\b(?:increase|grow|improve)\s+(?:my\s+)?income\b",
        lower,
    )
    profile_review_request = re.search(
        r"\b(?:review|use|assess|analy[sz]e)\b[^.!?]{0,100}"
        r"\b(?:the\s+)?(?:approved\s+)?business\s+profile\b",
        lower,
    )
    opportunity_request = re.search(
        r"\b(?:identify|find|suggest|recommend)\b[^.!?]{0,120}"
        r"\b(?:income|revenue|opportunit(?:y|ies))\b",
        lower,
    )
    business_income_review_requested = bool(
        legacy_business_income_review or (profile_review_request and opportunity_request)
    )
    evidence: list[InterpretationEvidence] = []
    clarifications: list[Clarification] = []
    context_requirements: list[str] = []
    for correction in norm.spelling_corrections:
        evidence.append(
            _evidence(
                field_path="normalized_instruction",
                source="normalized",
                source_text=correction.original,
                normalized_value=correction.replacement,
                confidence=correction.confidence,
                rule_id=f"spelling.{correction.source}",
            )
        )

    no_send = _contains_any(lower, _NO_SEND_PATTERNS)
    conditional_send = _contains_any(lower, _CONDITIONAL_SEND_PATTERNS)
    send_contradiction = (
        _contains_any(lower, _SEND_CONTRADICTION_PATTERNS) or (no_send and _contains_unnegated_send(lower))
    ) and not conditional_send
    wants_send = _contains_unnegated_send(lower) and not conditional_send
    wants_business_profile = _contains_any(lower, _BUSINESS_PROFILE_READ_PATTERNS)
    uses_business_profile = _contains_any(lower, _BUSINESS_PROFILE_CONTEXT_PATTERNS)
    wants_draft = _contains_any(lower, _DRAFT_PATTERNS)
    wants_qualify = _contains_any(lower, _QUALIFY_PATTERNS)
    wants_email_read = _contains_any(lower, _EMAIL_READ_PATTERNS)
    internal_crm_requested = _contains_any(lower, _INTERNAL_CRM_PATTERNS)
    crm_write_requested = _contains_any(lower, _CRM_UPDATE_PATTERNS) and not _contains_any(
        lower, _CRM_NEGATION_PATTERNS
    )
    internal_crm_read = (
        lexical_frame.internal_crm_read or _contains_any(lower, _INTERNAL_CRM_READ_PATTERNS)
    ) and not _contains_any(lower, _INTERNAL_CRM_READ_NEGATION_PATTERNS)
    internal_crm_as_source = (
        re.search(r"\bfrom\s+(?:the\s+)?internal\s+(?:ajenda\s+)?crm\b", lower) is not None
        or re.search(r"\bfrom\s+(?:the\s+)?ajenda\s+internal\s+crm\b", lower) is not None
        or re.search(r"\b(?:already\s+)?saved\s+in\s+(?:the\s+)?(?:ajenda\s+)?internal\s+crm\b", lower) is not None
    )
    explicit_internal_crm_read = bool(
        re.search(
            r"\b(?:review|inspect|read|check|list|query|summarize|compare|rank)\b"
            r"[^.!?]{0,120}\b(?:ajenda(?:['\u2019]s)?\s+crm|ajenda\s+internal\s+crm|internal\s+(?:ajenda\s+)?crm)\b",
            lower,
        )
    )
    if crm_write_requested and internal_crm_requested and not explicit_internal_crm_read:
        internal_crm_read = False
    # Read-back after a governed persistence is an acceptance/effect-verification
    # obligation of the write lane, not a second user-requested CRM read job.
    if _CRM_READBACK_VERIFICATION_PATTERN.search(lower) and not internal_crm_as_source:
        internal_crm_read = False
    explicit_hubspot_record_read = bool(re.search(r"\buse\s+(?:the\s+)?(?:hubspot|crm)\s+records?\b", lower))
    wants_crm_read = (
        (
            internal_crm_read
            or (
                (explicit_hubspot_record_read or _contains_any(lower, _CRM_READ_PATTERNS))
                and not internal_crm_requested
            )
        )
        and (internal_crm_read or not _contains_any(lower, _CRM_READ_NEGATION_PATTERNS))
        and (internal_crm_read or explicit_hubspot_record_read or not crm_write_requested)
        and (internal_crm_read or explicit_hubspot_record_read or not _contains_any(lower, _CRM_NEGATION_PATTERNS))
    )
    wants_salesforce_query = _contains_any(lower, _SALESFORCE_QUERY_PATTERNS)
    connector_read = wants_email_read or wants_crm_read or wants_salesforce_query
    explicit_prospect_research = bool(re.search(r"\b(?:prospects?|competitors?|companies\s+in)\b", lower))
    explicit_research_verb = bool(re.search(r"\b(?:research|discover|find)\b", lower))
    hubspot_as_research_source = bool(
        re.search(r"\bfrom\s+hubspot\b", lower) or re.search(r"\bcompanies\b.{0,80}\bhubspot\s+records?\b", lower)
    )
    direct_crm_record_read = _DIRECT_CRM_RECORD_READ.search(lower) is not None
    explicit_qualification_request = bool(re.search(r"\b(?:qualify|score|rank|rate|grade)\b", lower))
    crm_only_ranking = internal_crm_read and explicit_qualification_request and not explicit_research_verb
    if direct_crm_record_read and not explicit_qualification_request and not explicit_research_verb:
        wants_qualify = False
    # Direct CRM-record requests require the CRM authority as their source of
    # truth.  This prevents resolver fallback to public web discovery when the
    # adapter cannot represent an unsupported CRM scope (for example a market
    # wide location filter).
    if (internal_crm_read or internal_crm_as_source) and "internal_crm_source" not in context_requirements:
        context_requirements.append("internal_crm_source")
    elif direct_crm_record_read and not explicit_research_verb and "hubspot_source" not in context_requirements:
        context_requirements.append("hubspot_source")
    wants_research = (
        _contains_any(lower, _RESEARCH_PATTERNS)
        and (not direct_crm_record_read or explicit_research_verb)
        and (not connector_read or explicit_prospect_research or hubspot_as_research_source)
    )
    if internal_crm_as_source:
        # "From internal CRM" names the authoritative dataset. The verb
        # "find" must not also create a public-discovery branch.
        wants_research = False
    if crm_only_ranking:
        # Ranking persisted CRM records is qualification over an internal
        # source. The words "companies in ..." must not turn it into public
        # discovery unless the operator explicitly asks to research/find them.
        wants_research = False
    wants_research_report = _REPORT_SYNTHESIS_REQUEST.search(text) is not None and not business_income_review_requested
    # "Research companies in X from HubSpot" is market discovery using CRM as a source,
    # not a pure HubSpot record-read mission.
    if wants_research and hubspot_as_research_source and explicit_prospect_research:
        wants_crm_read = False
        connector_read = wants_email_read or wants_crm_read or wants_salesforce_query
    wants_observe = _contains_any(lower, _OBSERVE_CONTACT_PATTERNS)
    # Enrich only when explicitly requested — not invented from draft+qualify.
    wants_enrich = _contains_any(lower, _ENRICH_PATTERNS)
    wants_calendar = _contains_any(lower, _CALENDAR_PATTERNS)
    no_crm = _contains_any(lower, _CRM_NEGATION_PATTERNS)
    wants_crm = _contains_any(lower, _CRM_UPDATE_PATTERNS) and not no_crm
    wants_internal_crm = wants_crm and internal_crm_requested
    no_publish = _contains_any(lower, _PUBLISH_NEGATION_PATTERNS)
    wants_publish = _contains_any(lower, _PUBLISH_PATTERNS) and not no_publish
    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None
    # Wave A operator reads — fail closed against publish/write collisions.
    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish
    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)
    wants_contacts_read = (
        _contains_any(lower, _CONTACTS_READ_PATTERNS)
        and not wants_crm
        and not _contains_any(lower, _NO_EXTERNAL_ACTION_PATTERNS)
    )

    outcomes: list[CanonicalOutcome] = []
    if wants_business_profile:
        outcomes.append("read_business_profile")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_business_profile",
                source="explicit",
                source_text=text[:240],
                normalized_value="read_business_profile",
                confidence=0.95,
                rule_id="profile.governed_memory_read",
            )
        )
    if wants_research:
        outcomes.append("research_prospects")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.research_prospects",
                source="inferred_deterministic",
                source_text=text[:200],
                normalized_value="research_prospects",
                confidence=0.9,
                rule_id="alias.research",
            )
        )
    if wants_research_report:
        outcomes.append("synthesize_research_report")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.synthesize_research_report",
                source="explicit",
                source_text=text[:240],
                normalized_value="synthesize_research_report",
                confidence=0.95,
                rule_id="deliverable.research_report",
            )
        )
    if wants_qualify and not (direct_crm_record_read and not explicit_qualification_request):
        outcomes.append("qualify_prospects")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.qualify_prospects",
                source="inferred_deterministic",
                source_text=text[:200],
                normalized_value="qualify_prospects",
                confidence=0.9,
                rule_id="alias.qualify",
            )
        )
    # Ability vocabulary layer (score/rank/… → canonical outcomes).
    for vocab_hit in match_outcome_phrases(text):
        # Phrase/pattern matching is intentionally broad for legacy connector
        # wording, but a negated CRM clause must never create a read_crm outcome.
        if vocab_hit.outcome == "read_crm" and not wants_crm_read:
            continue
        if vocab_hit.outcome == "qualify_prospects" and direct_crm_record_read and not explicit_qualification_request:
            continue
        if vocab_hit.outcome == "read_contacts" and not wants_contacts_read:
            continue
        if vocab_hit.outcome not in outcomes:
            outcomes.append(vocab_hit.outcome)
            evidence.append(
                _evidence(
                    field_path=f"requested_outcomes.{vocab_hit.outcome}",
                    source="inferred_deterministic",
                    source_text=vocab_hit.source_text,
                    normalized_value=vocab_hit.outcome,
                    confidence=vocab_hit.confidence,
                    rule_id=vocab_hit.rule_id,
                )
            )
            if vocab_hit.outcome == "qualify_prospects":
                wants_qualify = True
            if vocab_hit.outcome == "observe_contacts":
                wants_observe = True
    if wants_observe:
        if "observe_contacts" not in outcomes:
            outcomes.append("observe_contacts")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.observe_contacts",
                source="explicit",
                normalized_value="observe_contacts",
                confidence=0.95,
                rule_id="alias.observe_contacts",
            )
        )
    if wants_enrich:
        outcomes.append("enrich_contacts")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.enrich_contacts",
                source="explicit",
                normalized_value="enrich_contacts",
                confidence=0.95,
                rule_id="alias.enrich",
            )
        )
    if wants_email_read and "read_email" not in outcomes:
        outcomes.append("read_email")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_email",
                source="explicit",
                normalized_value="read_email",
                confidence=0.95,
                rule_id="connector.gmail_read",
            )
        )
    if wants_crm_read and "read_crm" not in outcomes:
        outcomes.append("read_crm")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_crm",
                source="explicit",
                normalized_value="read_crm",
                confidence=0.95,
                rule_id="connector.hubspot_read",
            )
        )
    if business_income_review_requested and "review_business_income" not in outcomes:
        outcomes.append("review_business_income")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.review_business_income",
                source="inferred_deterministic",
                source_text=text[:240],
                normalized_value="review_business_income",
                confidence=0.9,
                rule_id="review.business_income",
            )
        )
    if "evaluate_goal_progress" in outcomes:
        evidence.append(
            _evidence(
                field_path="requested_outcomes.evaluate_goal_progress",
                source="explicit",
                source_text=text[:240],
                normalized_value="evaluate_goal_progress",
                confidence=0.95,
                rule_id="analysis.evaluate_goal_progress",
            )
        )
    # HubSpot-as-source prospect research: one research_prospects outcome (not dual read_crm).
    # Resolver uses context_requirements hubspot_source to require CRM-bound sales.research.
    if hubspot_as_research_source and "research_prospects" in outcomes:
        outcomes = [o for o in outcomes if o != "read_crm"]
        if "hubspot_source" not in context_requirements:
            context_requirements.append("hubspot_source")
    if _CRM_READBACK_VERIFICATION_PATTERN.search(lower) and not internal_crm_as_source:
        outcomes = [o for o in outcomes if o != "read_crm"]
    if wants_salesforce_query and "query_salesforce" not in outcomes:
        outcomes.append("query_salesforce")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.query_salesforce",
                source="explicit",
                normalized_value="query_salesforce",
                confidence=0.95,
                rule_id="connector.salesforce_query",
            )
        )
    if wants_draft:
        outcomes.append("prepare_outreach")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.prepare_outreach",
                source="inferred_deterministic",
                normalized_value="prepare_outreach",
                confidence=0.9,
                rule_id="alias.draft",
            )
        )
    if wants_send:
        outcomes.append("send_outreach")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.send_outreach",
                source="explicit",
                normalized_value="send_outreach",
                confidence=0.95,
                rule_id="alias.send",
            )
        )
    if wants_calendar:
        outcomes.append("read_calendar")
    if wants_linkedin_read and "read_linkedin" not in outcomes:
        outcomes.append("read_linkedin")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_linkedin",
                source="explicit",
                normalized_value="read_linkedin",
                confidence=0.95,
                rule_id="connector.linkedin_profile_read",
            )
        )
    if wants_github_read and "read_github" not in outcomes:
        outcomes.append("read_github")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_github",
                source="explicit",
                normalized_value="read_github",
                confidence=0.95,
                rule_id="connector.github_repo_read",
            )
        )
    if wants_contacts_read and "read_contacts" not in outcomes:
        outcomes.append("read_contacts")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.read_contacts",
                source="explicit",
                normalized_value="read_contacts",
                confidence=0.95,
                rule_id="connector.google_contacts_read",
            )
        )

    if wants_crm:
        if wants_internal_crm:
            outcomes = [item for item in outcomes if item != "update_crm"]
        outcomes.append("persist_internal_crm" if wants_internal_crm else "update_crm")
    if wants_publish:
        outcomes.append("publish_content")

    # Calendar write/create language is understood via connector schema but not runtime-bound.
    calendar_write_requested = _contains_any(lower, _CALENDAR_MUTATION_PATTERNS)
    calendar_read_intent = bool(
        re.search(
            r"\b(?:what(?:'s| is)|show|check|read|upcoming|brief(?:ing)?)\b.{0,40}\b(?:calend[ae]r|schedule)\b"
            r"|\b(?:calend[ae]r|schedule)\b.{0,40}\b(?:what|show|check|read|upcoming|brief)\b",
            lower,
            flags=re.IGNORECASE,
        )
    )
    if calendar_write_requested and "read_calendar" in outcomes and not calendar_read_intent:
        outcomes = [o for o in outcomes if o != "read_calendar"]

    # Optional fuzzy candidates only for unresolved outcome language (never ability select).
    # Use set[str] so mypy accepts the fuzzy helper signature (not a Literal union set).
    fuzzy_already: set[str] = {str(item) for item in outcomes}
    # Explicit draft language is already handled by the deterministic draft
    # patterns; prevent fuzzy matching from misclassifying "prepare drafts" as
    # the unrelated accounting outcome "prepare invoice drafts".
    if wants_draft:
        fuzzy_already.add("prepare_outreach")
        fuzzy_already.add("prepare_invoice_drafts")
    if calendar_write_requested and not calendar_read_intent:
        # Do not let fuzzy re-introduce read_calendar from "my calendar" / "schedule" aliases.
        fuzzy_already.add("read_calendar")
    fuzzy_hits, fuzzy_components = fuzzy_outcome_candidates(
        text,
        enabled=bool(fuzzy_enabled),
        already=fuzzy_already,
    )
    components_active.extend(c for c in fuzzy_components if c not in components_active)
    medium_fuzzy: list[str] = []
    for fuzzy_hit in fuzzy_hits:
        if fuzzy_hit.outcome == "read_crm" and (no_crm or not wants_crm_read):
            continue
        # Mentioning internal CRM records as a read source must not be
        # promoted by fuzzy vocabulary into a CRM write outcome.
        if (
            fuzzy_hit.outcome in {"update_crm", "persist_internal_crm"}
            and internal_crm_read
            and not crm_write_requested
        ):
            continue
        if fuzzy_hit.outcome == "send_outreach" and (no_send or conditional_send):
            continue
        # Browser deliverable language such as "return the final URL" can
        # score falsely against the legacy "return the contact info" alias.
        # Once an explicit web observation is present, require actual contact
        # wording before admitting observe_contacts from fuzzy matching.
        if (
            fuzzy_hit.outcome == "observe_contacts"
            and ("observe_web_page" in outcomes or "evaluate_goal_progress" in outcomes)
            and not _contains_any(lower, _OBSERVE_CONTACT_PATTERNS)
        ):
            continue
        fuzzy_connector_guards = {
            "read_email": wants_email_read,
            "read_crm": wants_crm_read,
            "read_calendar": wants_calendar,
            "read_linkedin": wants_linkedin_read,
            "read_github": wants_github_read,
            "read_contacts": wants_contacts_read,
            "query_salesforce": wants_salesforce_query,
        }
        if fuzzy_hit.outcome in fuzzy_connector_guards and not fuzzy_connector_guards[fuzzy_hit.outcome]:
            continue
        if fuzzy_hit.band == "high" and fuzzy_hit.outcome not in outcomes:
            if calendar_write_requested and not calendar_read_intent and fuzzy_hit.outcome == "read_calendar":
                continue
            outcomes.append(fuzzy_hit.outcome)
            evidence.append(
                _evidence(
                    field_path=f"requested_outcomes.{fuzzy_hit.outcome}",
                    source="inferred_fuzzy",
                    source_text=fuzzy_hit.matched_alias,
                    normalized_value=fuzzy_hit.outcome,
                    confidence=min(0.89, fuzzy_hit.score / 100.0),
                    rule_id="fuzzy.outcome_high",
                )
            )
        elif fuzzy_hit.band == "medium":
            medium_fuzzy.append(f"{fuzzy_hit.matched_alias}≈{fuzzy_hit.outcome}({fuzzy_hit.score:.0f})")

    # Structured send policy (authoritative for downstream).
    # Conditional approval outranks bare "do not send" when both appear
    # ("do not send anything until I approve").
    constraints: list[str] = []
    forbidden: list[str] = []
    contradictions: list[Contradiction] = []
    if send_contradiction:
        contradictions.append(
            Contradiction(
                field_path="send_policy",
                first_span="send",
                second_span="do not send",
                first_value="allow",
                second_value="forbid",
                risk="high",
                resolution_status="unresolved",
                rule_id="contradiction.send_allow_forbid",
            )
        )
        clarifications.append(
            _restatement(
                field="send_policy",
                understood="the mission contains both send and do-not-send instructions",
                missing="the external-send policy is contradictory",
                include_instruction="one unambiguous choice: draft only, send now, or send only after approval",
                reason="Contradictory external-effect instructions fail closed.",
            )
        )
    if no_crm:
        forbidden.append("gtm.crm_upsert")
        forbidden.append("record.write")
        constraints.append("Do not write contacts or CRM records")
        if "update_crm" in outcomes:
            outcomes = [o for o in outcomes if o != "update_crm"]
        if "persist_internal_crm" in outcomes:
            outcomes = [o for o in outcomes if o != "persist_internal_crm"]
    if no_publish:
        forbidden.append("gtm.social_publish")
        constraints.append("Do not publish or post to social channels")
        if "publish_content" in outcomes:
            outcomes = [o for o in outcomes if o != "publish_content"]
    if conditional_send:
        send_policy = SendPolicy(
            mode="conditional",
            condition="approval",
            source="explicit",
            confidence=0.95,
            rule_id="policy.send_after_approval",
        )
        constraints.append("Send only after approval")
        forbidden.append("gtm.email_send")
        evidence.append(
            _evidence(
                field_path="send_policy",
                source="explicit",
                normalized_value="conditional:approval",
                confidence=0.95,
                rule_id="policy.send_after_approval",
            )
        )
        # Desired but deferred — do not emit send_outreach as ready outcome.
        if "send_outreach" in outcomes:
            outcomes = [o for o in outcomes if o != "send_outreach"]
    elif no_send or (wants_draft and not wants_send):
        send_policy = SendPolicy(
            mode="forbid",
            condition="none",
            source="explicit" if no_send else "inferred_deterministic",
            confidence=0.98 if no_send else 0.9,
            rule_id="negation.no_send" if no_send else "negation.draft_only",
        )
        constraints.append("Do not send messages")
        forbidden.extend(["gtm.email_send"])
        if "send_outreach" in outcomes:
            outcomes = [o for o in outcomes if o != "send_outreach"]
        evidence.append(
            _evidence(
                field_path="send_policy",
                source=send_policy.source,
                normalized_value="forbid",
                confidence=send_policy.confidence,
                rule_id=send_policy.rule_id,
            )
        )
    elif wants_send:
        send_policy = SendPolicy(
            mode="allow",
            condition="none",
            source="explicit",
            confidence=0.9,
            rule_id="policy.send_allow",
        )
        evidence.append(
            _evidence(
                field_path="send_policy",
                source="explicit",
                normalized_value="allow",
                confidence=0.9,
                rule_id="policy.send_allow",
            )
        )
    else:
        send_policy = SendPolicy(mode="unknown", condition="none", source="unresolved", confidence=0.0)

    count = _extract_count(text)
    qualification_count = _extract_qualification_count(text)
    if count is not None:
        quantity: int | None = count
        quantity_provenance = "explicit"
        evidence.append(
            _evidence(
                field_path="requested_quantity",
                source="explicit",
                source_text=str(count),
                normalized_value=str(count),
                confidence=0.95,
                rule_id="entity.quantity",
            )
        )
    elif outcomes and any(o in outcomes for o in ("research_prospects", "qualify_prospects")):
        # Default quantity only for low-risk prospect research — not drafts/calendar.
        quantity = 3
        quantity_provenance = "system_default"
        evidence.append(
            _evidence(
                field_path="requested_quantity",
                source="system_default",
                normalized_value="3",
                confidence=0.55,
                rule_id="default.quantity_3",
            )
        )
    else:
        quantity = None
        quantity_provenance = None

    entities = _extract_target_entities(text)
    if not entities and wants_crm_read:
        entities = _extract_connector_company(text)
    # Multiple explicit market scopes are valid only when the instruction
    # clearly asks for a combined comparison. Exclusive wording such as
    # "but only" is a contradiction, not a second executable target. Fail
    # closed before job/ability resolution so downstream actions cannot mix
    # locations or industries from one ambiguous mission.
    market_entities = [
        entity for entity in entities if entity.type == "company" and entity.industry and entity.location
    ]
    exclusive_scope = bool(re.search(r"\b(?:but\s+only|instead|rather\s+than)\b", text, re.IGNORECASE))
    if exclusive_scope and len(market_entities) > 1:
        first, second = market_entities[0], market_entities[1]
        contradictions.append(
            Contradiction(
                field_path="target_entities.industry_location",
                first_span=f"{first.industry} in {first.location}",
                second_span=f"{second.industry} in {second.location}",
                first_value=f"{first.industry}|{first.location}",
                second_value=f"{second.industry}|{second.location}",
                risk="high",
                resolution_status="unresolved",
                rule_id="contradiction.target_scope_exclusive",
            )
        )
        clarifications.append(
            _restatement(
                field="target_scope",
                understood=f"the mission names both {first.industry} in {first.location} and {second.industry} in {second.location}",
                missing="the target industry and location are contradictory",
                include_instruction="one target industry and one location, or an explicit comparison request",
                reason="Contradictory target scope fails closed before runtime work is admitted.",
            )
        )
    if hubspot_as_research_source and "research_prospects" in outcomes and entities:
        head = entities[0]
        attrs = dict(head.attributes or {})
        attrs["research_source"] = "hubspot"
        entities[0] = head.model_copy(update={"attributes": attrs})
    # Named email recipients (draft-to-X without inventing discovery).
    for email_match in re.finditer(
        r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        text,
    ):
        email = email_match.group(1)
        if not any((e.email or "").lower() == email.lower() for e in entities):
            entities.append(
                TargetEntity(
                    type="recipient",
                    name=email.split("@")[0],
                    email=email,
                    provenance="explicit",
                    confidence=0.95,
                )
            )
            evidence.append(
                _evidence(
                    field_path="target_entities.email",
                    source="explicit",
                    source_text=email,
                    normalized_value=email,
                    confidence=0.95,
                    rule_id="entity.email_recipient",
                )
            )
    if entities and entities[0].type == "competitor_set" and entities[0].name:
        evidence.append(
            _evidence(
                field_path="target_entities[0]",
                source="explicit",
                source_text=(
                    f"competitors of {entities[0].name}"
                    + (f" in {entities[0].location}" if entities[0].location else "")
                ),
                normalized_value=f"competitors_of|{entities[0].name}|{entities[0].location or ''}",
                confidence=entities[0].confidence,
                rule_id="entity.competitors_of",
            )
        )
        label = f"competitors of {entities[0].name}" + (f" in {entities[0].location}" if entities[0].location else "")
    elif entities and entities[0].industry:
        evidence.append(
            _evidence(
                field_path="target_entities[0]",
                source="explicit",
                source_text=f"{entities[0].industry} in {entities[0].location}",
                normalized_value=f"{entities[0].industry}|{entities[0].location}",
                confidence=entities[0].confidence,
                rule_id="entity.industry_location",
            )
        )
        label = f"{entities[0].industry or 'target'} in {entities[0].location or 'specified market'}"
    elif entities and entities[0].email:
        label = entities[0].email
    elif entities and entities[0].name:
        label = entities[0].name
    else:
        label = "the requested market"

    # Clause coverage
    clause_models: list[InterpretedClause] = []
    unmatched: list[InterpretedClause] = []
    protected_entity_spans = [
        entity.name for entity in entities if isinstance(entity.name, str) and entity.name.strip()
    ]
    for index, clause_text in enumerate(_segment_clauses(text, protected_spans=protected_entity_spans)):
        mapped, material, recognized = _classify_clause(
            clause_text,
            profile_mission=wants_business_profile,
            external_action_forbidden=_contains_any(lower, _NO_EXTERNAL_ACTION_PATTERNS),
            business_income_review=business_income_review_requested,
            goal_progress_evaluation="evaluate_goal_progress" in outcomes,
        )
        if "verify_runtime_controls" in outcomes and re.search(
            r"\b(?:check|verify|evidence|runtime|network|secure|private|retry|audit|local)\b",
            clause_text,
            flags=re.IGNORECASE,
        ):
            recognized = True
            material = True
        if "observe_web_page" in outcomes and re.search(
            r"\b(?:observe|inspect|open|navigate|follow|click|extract|return|browser|link|title|visible|timestamp|blocked|final\s+url)\b",
            clause_text,
            flags=re.IGNORECASE,
        ):
            # Browser observation owns its bounded navigation/extraction clauses;
            # do not reject a valid step as an unrelated business clause.
            recognized = True
            material = True
            if "observe_web_page" not in mapped:
                mapped.append("observe_web_page")
        # Non-material filler: short politeness without risk keywords.
        if not material and len(clause_text.split()) <= 3:
            status = "non_material"
            material = False
            recognized = True
        elif recognized:
            status = "recognized"
        elif material:
            status = "unmatched"
        else:
            status = "non_material"
        clause = InterpretedClause(
            clause_id=f"c{index}",
            text=clause_text[:2000],
            status=status,  # type: ignore[arg-type]
            material=material,
            mapped_outcomes=mapped,
            reason=None if recognized else "No deterministic outcome or policy mapping",
        )
        clause_models.append(clause)
        if status == "unmatched" and material:
            unmatched.append(clause)

    material_total = sum(1 for c in clause_models if c.material)
    material_ok = sum(1 for c in clause_models if c.material and c.status == "recognized")
    coverage = (material_ok / material_total) if material_total else (1.0 if outcomes else 0.0)

    if "prepare_invoice_drafts" in outcomes:
        outcomes[:] = [item for item in outcomes if item != "prepare_outreach"]
    success = _success_for_outcomes(
        outcomes=outcomes,
        quantity=quantity,
        quantity_source=quantity_provenance or "unresolved",
        label=label,
    )

    understood_bits = [o.replace("_", " ") for o in outcomes]
    if entities:
        understood_bits.append(f"target {label}")
    if quantity is not None and quantity_provenance == "explicit":
        understood_bits.append(f"quantity {quantity}")
    understood = ", ".join(understood_bits) if understood_bits else None

    if not outcomes:
        if calendar_write_requested:
            # Connector schema clarification (calendar_write) is enough — avoid dual restatements.
            pass
        elif _looks_like_fragment(text):
            clarifications.append(
                _restatement(
                    field="requested_outcomes",
                    understood=None,
                    missing="this looks like a partial answer, not a complete mission instruction",
                    include_instruction=(
                        "the full objective, target market or scope, deliverable, "
                        "and whether sending or other external actions are permitted"
                    ),
                    reason=(
                        "Fragment answers cannot be merged into a prior MissionIntent; "
                        "each compose submit is a standalone raw instruction."
                    ),
                )
            )
        else:
            clarifications.append(
                _restatement(
                    field="requested_outcomes",
                    understood=None,
                    missing="an executable outcome could not be determined",
                    include_instruction=(
                        "what Ajenda should produce "
                        "(for example research prospects, qualify leads, prepare outreach, "
                        "send email only after approval, or calendar briefing)"
                    ),
                    reason="Could not map the instruction to a canonical executable outcome.",
                )
            )
    elif not success:
        clarifications.append(
            _restatement(
                field="success_criteria",
                understood=understood,
                missing="a measurable completion result could not be determined",
                include_instruction="the deliverable or evidence that should mark the mission complete",
                reason="Mapped outcomes did not yield a completion contract.",
            )
        )

    if unmatched:
        missing_bits = "; ".join(c.text[:120] for c in unmatched[:3])
        clarifications.append(
            _restatement(
                field="clause_coverage",
                understood=understood,
                missing=f"one or more material clauses were not understood ({missing_bits})",
                include_instruction=(
                    "those clauses rewritten in plain business language "
                    "(for example CRM updates, publishing, or external actions)"
                ),
                reason="Unmatched material clauses must not be silently dropped.",
            )
        )
        coverage = min(coverage, max(0.0, (material_ok) / max(material_total, 1)))

    if medium_fuzzy and not outcomes:
        clarifications.append(
            _restatement(
                field="requested_outcomes",
                understood=None,
                missing=(
                    "only medium-confidence phrase matches were found "
                    f"({'; '.join(medium_fuzzy[:3])}); outcomes must be clearer"
                ),
                include_instruction=(
                    "explicit executable outcomes using plain language "
                    "(research, qualify, prepare outreach, send after approval, calendar)"
                ),
                reason="Medium-confidence fuzzy matches must not authorize outcomes.",
            )
        )

    # Imperative calendar create/update/delete — intent understood, op deferred by connector schema.
    if calendar_write_requested:
        connector_note = restatement_for_deferred_op(connector_id="google_calendar", op="write")
        missing = connector_note or (
            "creating, updating, rescheduling, or deleting calendar events is not a composed "
            "runtime outcome yet (only calendar read/briefing is supported)"
        )
        clarifications.append(
            _restatement(
                field="calendar_write",
                understood=understood,
                missing=missing[:500],
                include_instruction=(
                    "whether to read existing calendar events instead, or omit calendar mutations from this mission"
                ),
                reason=(
                    "Connector capability schema: google_calendar write is deferred; "
                    "mutation language must not silently map to google_calendar.events_read."
                ),
            )
        )

    # Tag result-based publish so planners can expand research deps and bind content.
    if publish_result_based and "publish_content" in outcomes:
        if entities:
            entities = [
                entity.model_copy(update={"attributes": {**(entity.attributes or {}), "publish_result_based": True}})
                for entity in entities
            ]
        else:
            entities = [
                TargetEntity(
                    type="publish_context",
                    provenance="inferred_deterministic",
                    confidence=0.9,
                    attributes={"publish_result_based": True},
                )
            ]

    emailish = wants_draft or "email" in lower or "message" in lower
    if (
        emailish
        and send_policy.mode == "unknown"
        and not wants_draft
        and not wants_send
        and "send_outreach" not in outcomes
        and "read_email" not in outcomes
    ):
        clarifications.append(
            _restatement(
                field="send_permission",
                understood=understood,
                missing="the instruction does not clearly state whether Ajenda should prepare email only or also send it",
                include_instruction="whether sending is permitted or drafts must stay for review only",
                reason="External send permission is material and ambiguous.",
            )
        )

    # Prospect discovery without target scope (industry/location/competitors) — job-specific.
    if "research_prospects" in outcomes and not entities:
        # Allow trend-like research if no company-hunt shape; only restatement when
        # "companies" / prospect hunt language implies a bounded market.
        if re.search(r"\bcompanies\b|\bprospects\b|\bleads\b|\bcompetitors?\b", lower):
            clarifications.append(
                _restatement(
                    field="target_scope",
                    understood=understood,
                    missing="the target market is missing or could not be extracted",
                    include_instruction=(
                        "the industry or company type and the city/region, "
                        "or competitors of a named company in a location"
                    ),
                    reason="Prospect discovery requires a usable target scope.",
                )
            )

    approval = "review_before_external_action"
    if send_policy.mode == "allow":
        approval = "explicit_approval_for_send"
    elif send_policy.mode == "conditional":
        approval = "explicit_approval_for_send"
    elif wants_draft:
        approval = "review_before_external_action"

    if profile_context.get("company") or profile_context.get("business_name"):
        context_requirements.append("business_profile")
    if uses_business_profile and "business_profile" not in context_requirements:
        context_requirements.append("business_profile")

    # Keep the user's instruction as objective by default. Only rewrite when we have a
    # concrete target label — never "the requested market" which becomes a useless search query.
    objective = text
    if "read_revenue" in outcomes or "prepare_reconciliation" in outcomes:
        objective = f"{text} for this tenant"
    if "prepare_invoice_drafts" in outcomes:
        outcomes[:] = [
            item
            for item in outcomes
            if item not in {"prepare_outreach", "research_prospects", "qualify_prospects", "enrich_contacts"}
        ]
    if (
        "research_prospects" in outcomes
        and "prepare_outreach" in outcomes
        and send_policy.mode == "forbid"
        and entities
        and label != "the requested market"
    ):
        objective = f"Identify and prepare outreach for qualified {label} prospects without sending messages."

    # Split forbid concepts: action tokens vs display/legacy mix.
    forbidden_actions = [item for item in forbidden if "." in item and " " not in item]
    forbidden_canonical = [item for item in forbidden if item in CANONICAL_OUTCOMES]
    # Gate confidence on user-derived fields only — system defaults (e.g. qty=3)
    # must not fail ordinary research that intentionally omits quantity.
    confidences = [
        e.confidence
        for e in evidence
        if e.confidence is not None and e.source not in {"system_default", "profile_context"}
    ]
    min_conf = min(confidences) if confidences else None

    # Semantic units from clauses (coverage measured over material units).
    from backend.services.mission_composition.contracts import SemanticUnit

    semantic_units: list[SemanticUnit] = []
    unmatched_units: list[SemanticUnit] = []
    try:
        for clause in clause_models:
            unit = SemanticUnit(
                unit_id=clause.clause_id,
                kind="action" if clause.mapped_outcomes else "other",
                text=clause.text,
                accounted=clause.status == "recognized",
                mapped_outcomes=list(clause.mapped_outcomes),
                risk="high"
                if any(
                    token in clause.text.lower()
                    for token in ("delete", "charge", "invoice", "publish", "send", "overwrite")
                )
                else "low",
                reason=clause.reason,
            )
            semantic_units.append(unit)
            if clause.material and clause.status != "recognized":
                unmatched_units.append(unit)
    except Exception:
        semantic_units = []
        unmatched_units = []

    intent = MissionIntent(
        raw_instruction=raw_instruction,
        normalized_instruction=text,
        objective=objective,
        requested_outcomes=list(outcomes),
        requested_quantity=quantity,
        quantity_provenance=quantity_provenance,  # type: ignore[arg-type]
        qualification_quantity=qualification_count,
        send_policy=send_policy,
        target_entities=entities,
        constraints=constraints,
        forbidden_outcomes=forbidden,
        forbidden_actions=forbidden_actions,
        forbidden_canonical_outcomes=forbidden_canonical,
        success_criteria=success
        if success
        else [
            SuccessCriterion(
                description="Mission produces evidence-backed deliverables matching the stated objective",
                measurable=False,
            )
        ],
        urgency="normal",
        approval_preference=approval,
        budget_limits=None,
        context_requirements=context_requirements,
        ambiguity=clarifications,
        contradictions=contradictions,
        interpreted_clauses=clause_models,
        unmatched_material_clauses=unmatched,
        semantic_units=semantic_units,
        unmatched_material_units=unmatched_units,
        interpretation_evidence=evidence,
        coverage_score=round(coverage, 3),
        minimum_field_confidence=min_conf,
        components_available=list(dict.fromkeys([*components_active, "regex_core"])),
        components_executed=list(dict.fromkeys(components_active)),
        components_contributing=list(dict.fromkeys(components_active)),
        components_active=list(dict.fromkeys(components_active)),
        interpreter_version=INTERPRETER_VERSION,
    )
    from backend.services.mission_composition.readiness import evaluate_interpretation_readiness

    readiness = evaluate_interpretation_readiness(intent)
    return intent.model_copy(
        update={
            "interpretation_ready": readiness.ready,
            "interpretation_readiness_reasons": list(readiness.reasons),
            # Align ambiguity with readiness when restatement required.
            "ambiguity": intent.ambiguity
            if intent.ambiguity
            else (
                [
                    _restatement(
                        field="interpretation_readiness",
                        understood=objective[:240] if objective else None,
                        missing="; ".join(readiness.reasons)[:400],
                        include_instruction=(
                            "the full objective, target market or scope, deliverable, "
                            "and whether sending or other external actions are permitted"
                        ),
                        reason="Interpretation readiness policy failed.",
                    )
                ]
                if not readiness.ready
                else []
            ),
        }
    )
