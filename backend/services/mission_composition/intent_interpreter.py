"""Deterministic plain-language → MissionIntent interpreter.

Emits canonical outcome IDs, structured quantity / send policy, and restatement
requirements. Does not select actions, grant credentials, or queue work.

Each compose submit is a standalone raw instruction — no client fragment merge.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.contracts import (
    INTERPRETER_VERSION,
    CanonicalOutcome,
    Clarification,
    InterpretationEvidence,
    InterpretedClause,
    MissionIntent,
    SendPolicy,
    SuccessCriterion,
    TargetEntity,
)
from backend.services.mission_composition.interpretation.fuzzy import fuzzy_outcome_candidates
from backend.services.mission_composition.interpretation.normalize import normalize_instruction_text

_COMPONENTS_ACTIVE = ("regex_core",)

_SEND_PATTERNS = (
    r"\bsend\b",
    r"\bsending\b",
    r"\bdeliver\b",
    r"\bdispatch\b",
    r"\bmail them\b",
)
_NO_SEND_PATTERNS = (
    r"before anything is sent",
    r"do not send",
    r"don't send",
    r"dont send",
    r"without sending",
    r"bring them to me",
    r"review before",
    r"draft only",
    r"prepare drafts",
    r"no send",
)
_CONDITIONAL_SEND_PATTERNS = (
    r"send only after",
    r"after (?:i |my )?approv",
    r"once (?:i |you )?approv",
    r"until (?:i |you )?approv",
    r"hold until",
    r"nothing goes out without",
)
_DRAFT_PATTERNS = (
    r"\bdraft\b",
    r"introduction",
    r"outreach",
    r"personalized",
)
_QUALIFY_PATTERNS = (
    r"\bqualify\b",
    r"strong prospects",
    r"identify .* prospects",
    r"best (?:leads|prospects)",
)
_RESEARCH_PATTERNS = (
    r"\bresearch\b",
    r"\bfind\b",
    r"\bdiscover\b",
    r"companies in",
    r"prospects",
    r"competitors?",
    r"competors?",
)
_LOCATION_TRAILING_STOP = re.compile(
    r"\s+\b(?:"
    r"identify|find|discover|and|with|for|to|that|who|which|"
    r"strong|best|top|draft|enrich|qualify|send|prepare|"
    r"prospects?|competitors?|competors?|leads?"
    r")\b",
    re.IGNORECASE,
)
_ENRICH_PATTERNS = (
    r"\benrich\b",
    r"contact details",
    r"find emails",
)
_CALENDAR_PATTERNS = (
    r"\bcalendar\b",
    r"calendar briefing",
    r"read calendar",
    r"upcoming (?:calendar )?commitments",
    r"meeting prep",
    r"meeting brief",
)
# Mutation verbs only — naming HubSpot/CRM as a read source must not imply upsert.
_CRM_UPDATE_PATTERNS = (
    r"\bupdate (?:the )?(?:crm|pipeline|hubspot)\b",
    r"\blog (?:to |in |into )?(?:the )?crm\b",
    r"\blogs? (?:activity|to crm)\b",
    r"\bupsert\b",
    r"\bwrite (?:to |into )?(?:the )?crm\b",
    r"\bsync (?:to |into )?(?:the )?(?:crm|hubspot)\b",
    r"\bpush (?:to |into )?(?:the )?(?:crm|hubspot)\b",
)
# Publish/post verbs only — "prospects on LinkedIn" is research, not publishing.
_PUBLISH_PATTERNS = (
    r"\bpublish\b",
    r"\bpost(?:ing)? (?:to|on) (?:linkedin|social|twitter|x)\b",
    r"\bpost(?:ing)? .{0,48}\b(?:to|on) (?:linkedin|social|twitter|x)\b",
    r"\bshare (?:to|on) (?:linkedin|social)\b",
    r"\bpost (?:an? )?(?:update|announcement|message) (?:to|on)\b",
    r"\bsocial media post",
)
_COUNT_PATTERN = re.compile(r"\b(\d+|three|two|four|five|ten)\b", re.IGNORECASE)
_WORD_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
}
_INDUSTRY_LOCATION = re.compile(
    r"(?:^|[\s,;:])(?P<industry>[A-Za-z][A-Za-z\-/]{1,40}(?:\s+[A-Za-z][A-Za-z\-/]{1,40}){0,3})"
    r"\s+companies\s+in\s+(?P<location>[A-Za-z][A-Za-z.\-]{1,40}(?:\s+[A-Za-z][A-Za-z.\-]{1,40}){0,3})"
    r"(?=$|[\s,;.:]|\band\b)",
    re.IGNORECASE,
)
_LEADING_VERB_WORDS = frozenset(
    {
        "research",
        "find",
        "discover",
        "identify",
        "search",
        "locate",
        "analyze",
        "study",
        "review",
        "target",
    }
)
_FRAGMENT_HINTS = (
    r"^complete when\b",
    r"^when the email is sent\b",
    r"^just\b",
    r"^\d+\s*(companies|prospects|leads)?\.?$",
    r"^(two|three|four|five|ten)\s*(companies|prospects|leads)?\.?$",
    r"^[A-Za-z][A-Za-z.\-\s]{1,40}$",
)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|\band\b|;)\s*", re.IGNORECASE)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _extract_count(text: str) -> int | None:
    match = _COUNT_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group(1).lower()
    if raw.isdigit():
        return int(raw)
    return _WORD_COUNTS.get(raw)


def _extract_target_entities(text: str) -> list[TargetEntity]:
    match = _INDUSTRY_LOCATION.search(text)
    if match is None:
        return []
    industry_tokens = [token for token in match.group("industry").strip().split() if token]
    while industry_tokens and industry_tokens[0].lower() in _LEADING_VERB_WORDS:
        industry_tokens.pop(0)
    industry = " ".join(industry_tokens).strip(" ,.;:")
    location = match.group("location").strip(" ,.;:")
    stop = _LOCATION_TRAILING_STOP.search(f" {location}")
    if stop is not None:
        cut = max(0, stop.start() - 1)
        location = location[:cut].strip(" ,.;:")
    if not industry or not location:
        return []
    return [
        TargetEntity(
            type="company",
            industry=industry,
            location=location,
            provenance="explicit",
            confidence=0.95,
        )
    ]


def _restatement(
    *,
    field: str,
    understood: str | None,
    missing: str,
    include_instruction: str,
    reason: str,
) -> Clarification:
    parts: list[str] = []
    if understood:
        parts.append(f"I understood: {understood}.")
    parts.append(f"I cannot compose this mission reliably because {missing}.")
    parts.append(f"Please restate the complete mission and include {include_instruction}.")
    return Clarification(field=field, question=" ".join(parts), reason=reason)


def _looks_like_fragment(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 12:
        return True
    if len(stripped.split()) <= 6 and _contains_any(stripped.lower(), _FRAGMENT_HINTS):
        return True
    if len(stripped) < 80 and not _contains_any(
        stripped.lower(),
        _RESEARCH_PATTERNS + _DRAFT_PATTERNS + _SEND_PATTERNS + _QUALIFY_PATTERNS + _CALENDAR_PATTERNS,
    ):
        return True
    return False


def _evidence(
    *,
    field_path: str,
    source: str,
    source_text: str | None = None,
    normalized_value: str | None = None,
    confidence: float = 1.0,
    rule_id: str | None = None,
) -> InterpretationEvidence:
    return InterpretationEvidence(
        field_path=field_path,
        source=source,  # type: ignore[arg-type]
        source_text=source_text,
        normalized_value=normalized_value,
        confidence=confidence,
        rule_id=rule_id,
        interpreter_version=INTERPRETER_VERSION,
        components_active=list(_COMPONENTS_ACTIVE),
    )


def _success_for_outcomes(
    *,
    outcomes: list[CanonicalOutcome],
    quantity: int | None,
    quantity_source: str,
    label: str,
) -> list[SuccessCriterion]:
    """Display completion text from job contracts — not a data transport."""

    n = quantity if quantity is not None else 3
    success: list[SuccessCriterion] = []
    if "research_prospects" in outcomes or "qualify_prospects" in outcomes:
        qty_note = f"{n}" if quantity is not None else f"{n} (system default)"
        if quantity_source == "system_default":
            qty_note = f"{n} (system default)"
        success.append(
            SuccessCriterion(
                description=f"{qty_note} prospects contain company and qualification evidence for {label}",
                measurable=True,
            )
        )
    if "enrich_contacts" in outcomes:
        success.append(
            SuccessCriterion(
                description=f"{n} prospects include contact enrichment evidence",
                measurable=True,
            )
        )
    if "prepare_outreach" in outcomes:
        success.append(
            SuccessCriterion(
                description=f"{n} personalized introduction drafts are ready for review",
                measurable=True,
            )
        )
    if "send_outreach" in outcomes:
        success.append(
            SuccessCriterion(
                description="Provider returns an accepted-send result or message identifier for each authorized send",
                measurable=True,
            )
        )
    if "read_calendar" in outcomes:
        success.append(
            SuccessCriterion(
                description="Requested calendar results are returned with provider evidence",
                measurable=True,
            )
        )
    if "update_crm" in outcomes:
        success.append(
            SuccessCriterion(
                description="CRM record changes are confirmed by provider response or readback",
                measurable=True,
            )
        )
    return success


def _segment_clauses(text: str) -> list[str]:
    parts = [p.strip(" ,.;") for p in _CLAUSE_SPLIT.split(text) if p and p.strip(" ,.;")]
    return parts if parts else [text.strip()]


def _classify_clause(clause: str) -> tuple[list[CanonicalOutcome], bool, bool]:
    """Return (outcomes, material, recognized)."""

    lower = clause.lower()
    outcomes: list[CanonicalOutcome] = []
    if _contains_any(lower, _RESEARCH_PATTERNS):
        outcomes.append("research_prospects")
    if _contains_any(lower, _QUALIFY_PATTERNS):
        outcomes.append("qualify_prospects")
    if _contains_any(lower, _ENRICH_PATTERNS):
        outcomes.append("enrich_contacts")
    if _contains_any(lower, _DRAFT_PATTERNS):
        outcomes.append("prepare_outreach")
    if _contains_any(lower, _SEND_PATTERNS) and not _contains_any(lower, _NO_SEND_PATTERNS):
        outcomes.append("send_outreach")
    if _contains_any(lower, _CALENDAR_PATTERNS):
        outcomes.append("read_calendar")
    if _contains_any(lower, _CRM_UPDATE_PATTERNS):
        outcomes.append("update_crm")
    if _contains_any(lower, _PUBLISH_PATTERNS):
        outcomes.append("publish_content")

    material = bool(outcomes) or _contains_any(
        lower,
        _NO_SEND_PATTERNS
        + _CONDITIONAL_SEND_PATTERNS
        + _CRM_UPDATE_PATTERNS
        + _PUBLISH_PATTERNS
        + (r"\bapprov", r"\bdelet", r"\bcharg", r"\binvoice"),
    )
    # Bare location/count fragments treated as material when short.
    if not material and (re.search(r"\b\d+\b", lower) or len(clause.split()) <= 4):
        material = True
    recognized = bool(outcomes) or _contains_any(lower, _NO_SEND_PATTERNS + _CONDITIONAL_SEND_PATTERNS)
    # Industry+location span is recognized material even without a verb.
    if _INDUSTRY_LOCATION.search(clause):
        material = True
        recognized = True
    return outcomes, material, recognized


def interpret_instruction(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
    spelling_enabled: bool | None = None,
    fuzzy_enabled: bool | None = None,
) -> MissionIntent:
    """Extract a candidate MissionIntent without granting execution authority."""

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
    wants_send = _contains_any(lower, _SEND_PATTERNS) and not no_send and not conditional_send
    wants_draft = _contains_any(lower, _DRAFT_PATTERNS)
    wants_qualify = _contains_any(lower, _QUALIFY_PATTERNS)
    wants_research = _contains_any(lower, _RESEARCH_PATTERNS)
    # Enrich only when explicitly requested — not invented from draft+qualify.
    wants_enrich = _contains_any(lower, _ENRICH_PATTERNS)
    wants_calendar = _contains_any(lower, _CALENDAR_PATTERNS)
    wants_crm = _contains_any(lower, _CRM_UPDATE_PATTERNS)
    wants_publish = _contains_any(lower, _PUBLISH_PATTERNS)

    outcomes: list[CanonicalOutcome] = []
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
    if wants_qualify:
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
    if wants_crm:
        outcomes.append("update_crm")
    if wants_publish:
        outcomes.append("publish_content")

    # Optional fuzzy candidates only for unresolved outcome language (never ability select).
    fuzzy_hits, fuzzy_components = fuzzy_outcome_candidates(
        text,
        enabled=bool(fuzzy_enabled),
        already=set(outcomes),
    )
    components_active.extend(c for c in fuzzy_components if c not in components_active)
    medium_fuzzy: list[str] = []
    for hit in fuzzy_hits:
        if hit.band == "high" and hit.outcome not in outcomes:
            outcomes.append(hit.outcome)
            evidence.append(
                _evidence(
                    field_path=f"requested_outcomes.{hit.outcome}",
                    source="inferred_fuzzy",
                    source_text=hit.matched_alias,
                    normalized_value=hit.outcome,
                    confidence=min(0.89, hit.score / 100.0),
                    rule_id="fuzzy.outcome_high",
                )
            )
        elif hit.band == "medium":
            medium_fuzzy.append(f"{hit.matched_alias}≈{hit.outcome}({hit.score:.0f})")

    # Structured send policy (authoritative for downstream).
    # Conditional approval outranks bare "do not send" when both appear
    # ("do not send anything until I approve").
    constraints: list[str] = []
    forbidden: list[str] = []
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
        forbidden.extend(["send messages", "gtm.email_send"])
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
    elif outcomes and any(o in outcomes for o in ("research_prospects", "qualify_prospects", "prepare_outreach")):
        quantity = 3
        quantity_provenance = "system_default"
        evidence.append(
            _evidence(
                field_path="requested_quantity",
                source="system_default",
                normalized_value="3",
                confidence=0.5,
                rule_id="default.quantity_3",
            )
        )
    else:
        quantity = None
        quantity_provenance = None

    entities = _extract_target_entities(text)
    if entities:
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
    else:
        label = "the requested market"

    # Clause coverage
    clause_models: list[InterpretedClause] = []
    unmatched: list[InterpretedClause] = []
    for index, clause_text in enumerate(_segment_clauses(text)):
        mapped, material, recognized = _classify_clause(clause_text)
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
        if _looks_like_fragment(text):
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
                    missing="a business outcome could not be determined",
                    include_instruction=(
                        "what Ajenda should produce "
                        "(for example research prospects, qualify leads, prepare outreach, "
                        "send email only after approval, or calendar briefing)"
                    ),
                    reason="Could not map the instruction to a canonical business outcome.",
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
                    "explicit business outcomes using plain language "
                    "(research, qualify, prepare outreach, send after approval, calendar)"
                ),
                reason="Medium-confidence fuzzy matches must not authorize outcomes.",
            )
        )

    # Publish is not executable in this catalog generation — fail closed if requested.
    if "publish_content" in outcomes:
        clarifications.append(
            _restatement(
                field="publish_content",
                understood=understood,
                missing="publishing or social posting was requested but is not a composed runtime outcome yet",
                include_instruction="whether to omit publishing, or restate only outcomes Ajenda can run today",
                reason="publish_content is recognized but not runtime-bound in the job catalog.",
            )
        )

    emailish = wants_draft or "email" in lower or "message" in lower
    if (
        emailish
        and send_policy.mode == "unknown"
        and not wants_draft
        and not wants_send
        and "send_outreach" not in outcomes
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

    # Prospect discovery without target scope (industry/location) — job-specific.
    if "research_prospects" in outcomes and not entities:
        # Allow trend-like research if no company-hunt shape; only restatement when
        # "companies" / prospect hunt language implies a bounded market.
        if re.search(r"\bcompanies\b|\bprospects\b|\bleads\b", lower):
            clarifications.append(
                _restatement(
                    field="target_scope",
                    understood=understood,
                    missing="the target market is missing or could not be extracted",
                    include_instruction="the industry or company type and the city, region, or service area",
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

    objective = text if len(text) <= 500 else text[:497] + "..."
    if "research_prospects" in outcomes and "prepare_outreach" in outcomes and send_policy.mode == "forbid":
        objective = f"Identify and prepare outreach for qualified {label} prospects without sending messages."

    return MissionIntent(
        objective=objective,
        requested_outcomes=list(outcomes),
        requested_quantity=quantity,
        quantity_provenance=quantity_provenance,  # type: ignore[arg-type]
        send_policy=send_policy,
        target_entities=entities,
        constraints=constraints,
        forbidden_outcomes=forbidden,
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
        interpreted_clauses=clause_models,
        unmatched_material_clauses=unmatched,
        interpretation_evidence=evidence,
        coverage_score=round(coverage, 3),
        components_active=list(dict.fromkeys(components_active)),
        interpreter_version=INTERPRETER_VERSION,
    )
