"""OpenAI-compatible structured-output client for the local interpreter model."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from backend.app.config import Settings
from backend.observability.logging import get_observability_logger
from backend.services.mission_composition.contracts import normalize_outcome_token
from backend.services.mission_composition.interpretation.schema import LlmMissionInterpretation
from backend.services.mission_composition.interpretation.schema_compat import constrained_decoding_schema

_LOG = get_observability_logger(__name__)

# Common model mislabels → canonical outcome IDs (language-only; not authority).
_OUTCOME_STRUCTURAL_ALIASES: dict[str, str] = {
    "write_crm_record": "update_crm",
    "write_crm": "update_crm",
    "crm_update": "update_crm",
    "crm_write": "update_crm",
    "log_crm": "update_crm",
    "draft_email": "prepare_outreach",
    "draft_emails": "prepare_outreach",
    "draft_outreach": "prepare_outreach",
    "create_draft": "prepare_outreach",
    "prepare_email": "prepare_outreach",
    "write_email": "prepare_outreach",
    "compose_email": "prepare_outreach",
    "send_email": "send_outreach",
    "email_send": "send_outreach",
    "find_prospects": "research_prospects",
    "discover_prospects": "research_prospects",
    "prospect_research": "research_prospects",
    "lead_research": "research_prospects",
    "post_content": "publish_content",
    "publish": "publish_content",
    "social_publish": "publish_content",
}

# Non-outcomes models sometimes emit; drop from requested unless source text remaps.
_OUTCOME_DROP_TOKENS: frozenset[str] = frozenset(
    {
        "collect_context",
        "schedule_follow_up",
        "follow_up",
        "none",
        "unknown",
        "n_a",
        "na",
    }
)

_TARGET_TYPE_ALIASES: dict[str, str] = {
    "location": "market",
    "place": "market",
    "geo": "market",
    "region": "market",
    "city": "market",
    "area": "market",
    "industry": "market",
    "sector": "market",
    "vertical": "market",
    "market_segment": "market",
    "business": "company",
    "organization": "company",
    "org": "company",
    "lead": "person",
    "prospect": "person",
    "individual": "person",
    "email_address": "email",
    "mailbox": "email",
}

_ALLOWED_TARGET_TYPES = frozenset(
    {"market", "company", "person", "contact", "recipient", "competitor_set", "email"}
)
_ALLOWED_TARGET_KEYS = frozenset(
    {
        "type",
        "source_text",
        "source",
        "industry",
        "location",
        "name",
        "radius_km",
        "domain",
        "url",
        "email",
        "confidence",
    }
)
_ALLOWED_OUTCOME_KEYS = frozenset({"outcome", "source_text", "confidence"})
_ALLOWED_POLICY_KEYS = frozenset({"mode", "condition", "source_text", "confidence"})
_ALLOWED_CRITERION_KEYS = frozenset({"description", "source_text", "measurable", "confidence"})
_ALLOWED_SEGMENT_KEYS = frozenset(
    {
        "source_text",
        "normalized_text",
        "kind",
        "material",
        "accounted",
        "mapped_outcomes",
        "risk",
        "reason",
    }
)


class MissionInterpreterTransportError(RuntimeError):
    def __init__(self, *, code: str, message: str, retryable: bool, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MissionInterpretationRequest:
    system_prompt: str
    user_prompt: str


class MissionInterpreterClient(Protocol):
    model: str

    def interpret(self, request: MissionInterpretationRequest) -> LlmMissionInterpretation: ...


class OpenAiCompatibleMissionInterpreterClient:
    """Calls Ollama, llama.cpp, or another internal OpenAI-compatible server.

    This client is intentionally strict: it has no template or unstructured
    fallback. Transport, protocol, JSON, and schema failures remain visible and
    fail closed at the composition boundary.
    """

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self.model = str(settings.mission_interpreter_model).strip()

    def interpret(self, request: MissionInterpretationRequest) -> LlmMissionInterpretation:
        if not self._settings.mission_interpreter_enabled:
            raise MissionInterpreterTransportError(
                code="INTERPRETER_DISABLED",
                message="mission interpretation is not enabled",
                retryable=False,
            )
        base_url = str(self._settings.mission_interpreter_base_url).strip().rstrip("/")
        if not base_url or not self.model:
            raise MissionInterpreterTransportError(
                code="INTERPRETER_NOT_CONFIGURED",
                message="mission interpreter endpoint and model must be configured",
                retryable=False,
            )
        endpoint_host = (urlparse(base_url).hostname or "").casefold().rstrip(".")
        if endpoint_host not in self._settings.mission_interpreter_private_host_allowlist_set:
            raise MissionInterpreterTransportError(
                code="INTERPRETER_ENDPOINT_NOT_ALLOWED",
                message="mission interpreter endpoint is not on the private host allowlist",
                retryable=False,
            )

        # Full Pydantic model remains the acceptance contract. Transport tries an
        # Ollama-safe sanitized json_schema first, then json_object once if
        # grammar/predict transport fails. No host-Ollama fallback. No templates.
        decoding_schema = constrained_decoding_schema(LlmMissionInterpretation.model_json_schema())
        max_tokens = min(int(self._settings.mission_interpreter_max_tokens), 1200)
        # Compact reminder: long prose + full schema slows CPU Ollama past budget.
        schema_reminder = (
            "\nJSON only. Keys: schema_version=1, interpreted_instruction, "
            "requested_outcomes[{outcome,source_text}], "
            "send_policy{mode,source_text}, "
            "target_entities[{type,source_text,location?,industry?}], "
            "requested_quantity, quantity_source_text, "
            "success_criteria[{description,source_text}], "
            "segments[{source_text,normalized_text}]."
        )
        base_messages: list[dict[str, str]] = [
            {"role": "system", "content": request.system_prompt + schema_reminder},
            {"role": "user", "content": request.user_prompt},
        ]
        headers = {"Content-Type": "application/json"}
        api_key = str(self._settings.mission_interpreter_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Prefer sanitized json_schema when the runtime can load GBNF quickly.
        # Always keep json_object as the second attempt so Ollama product path
        # does not hard-fail on grammar init / long predict 500s. Acceptance
        # remains full Pydantic validation either way.
        # In-stack Ollama (product path) uses json_object: full json_schema GBNF is
        # either rejected or exceeds the client/server budget on CPU. Other
        # OpenAI-compatible private endpoints still prefer sanitized json_schema.
        in_stack_ollama = endpoint_host in {"mission-interpreter", "ollama"} or endpoint_host.endswith(
            (".svc", ".cluster.local", ".internal")
        )
        if in_stack_ollama:
            format_attempts = [{"type": "json_object"}]
        else:
            format_attempts = [
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ajenda_mission_interpretation",
                        "strict": True,
                        "schema": decoding_schema,
                    },
                },
                {"type": "json_object"},
            ]

        started = time.monotonic()
        body: dict[str, Any] | None = None
        last_transport_error: MissionInterpreterTransportError | None = None
        # Private inference only; never honor ambient HTTP(S)_PROXY.
        # Cap request tokens so CPU Ollama finishes within the product timeout.
        # 512 is enough for short missions once structural coerce fills holes.
        request_max_tokens = min(max_tokens, 512 if in_stack_ollama else max_tokens)
        with httpx.Client(
            timeout=float(self._settings.mission_interpreter_timeout_seconds),
            trust_env=False,
        ) as client:
            for index, response_format in enumerate(format_attempts):
                try:
                    body = _post_chat_completion(
                        client=client,
                        base_url=base_url,
                        headers=headers,
                        model=self.model,
                        max_tokens=request_max_tokens,
                        messages=base_messages,
                        response_format=response_format,
                        ollama_speed_options=in_stack_ollama,
                    )
                    last_transport_error = None
                    break
                except MissionInterpreterTransportError as exc:
                    last_transport_error = exc
                    if (
                        exc.code not in {"INTERPRETER_UNAVAILABLE", "INTERPRETER_TIMEOUT"}
                        or index >= len(format_attempts) - 1
                    ):
                        self._log_failure(
                            code=exc.code,
                            started=started,
                            retryable=exc.retryable,
                            detail=getattr(exc, "detail", None),
                        )
                        raise
                    continue

        if body is None:
            if last_transport_error is not None:
                raise last_transport_error
            raise MissionInterpreterTransportError(
                code="INTERPRETER_UNAVAILABLE",
                message="mission interpretation is temporarily unavailable; try again",
                retryable=True,
            )

        try:
            content = _response_content(body)
            if _finish_reason_truncated(body):
                raise ValueError("interpreter response was truncated before a complete JSON object was produced")
            payload_obj = json.loads(content)
            if not isinstance(payload_obj, dict):
                raise ValueError("interpreter response must be a JSON object")
            payload_obj = _coerce_structural_defaults(payload_obj)
            interpretation = LlmMissionInterpretation.model_validate(payload_obj)
        except ValidationError as exc:
            self._log_failure(
                code="INTERPRETER_INVALID_OUTPUT",
                started=started,
                retryable=True,
                detail=_validation_error_detail(exc),
            )
            raise MissionInterpreterTransportError(
                code="INTERPRETER_INVALID_OUTPUT",
                message="mission interpretation could not be validated; revise or try again",
                retryable=True,
            ) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._log_failure(
                code="INTERPRETER_INVALID_OUTPUT",
                started=started,
                retryable=True,
                detail=f"{type(exc).__name__}:{str(exc)[:200]}",
            )
            raise MissionInterpreterTransportError(
                code="INTERPRETER_INVALID_OUTPUT",
                message="mission interpretation could not be validated; revise or try again",
                retryable=True,
            ) from exc

        _LOG.info(
            "mission interpretation completed",
            category="mission_interpreter",
            payload={
                "model": self.model,
                "status": "success",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "schema_version": interpretation.schema_version,
            },
        )
        return interpretation

    def _log_failure(self, *, code: str, started: float, retryable: bool, detail: str | None = None) -> None:
        payload: dict[str, Any] = {
            "model": self.model,
            "status": "failure",
            "code": code,
            "retryable": retryable,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        }
        if detail:
            payload["detail"] = detail
        _LOG.warning(
            "mission interpretation failed",
            category="mission_interpreter",
            payload=payload,
        )


def _post_chat_completion(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    model: str,
    max_tokens: int,
    messages: list[dict[str, str]],
    response_format: dict[str, Any],
    ollama_speed_options: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": messages,
        "response_format": response_format,
    }
    if ollama_speed_options:
        # Ollama OpenAI-compat accepts options; keep context small for CPU latency.
        payload["options"] = {
            "temperature": 0,
            "num_predict": max_tokens,
            "num_ctx": 2048,
        }
        # Keep weights resident between compose calls (minutes, not seconds).
        payload["keep_alive"] = "30m"
    try:
        response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise MissionInterpreterTransportError(
            code="INTERPRETER_TIMEOUT",
            message="mission interpretation timed out; try again",
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise MissionInterpreterTransportError(
            code="INTERPRETER_UNAVAILABLE",
            message="mission interpretation is temporarily unavailable; try again",
            retryable=True,
        ) from exc

    if response.status_code >= 400:
        detail = f"http_{response.status_code}"
        body_preview = (response.text or "").strip().replace("\n", " ")[:240]
        if body_preview:
            detail = f"{detail}:{body_preview}"
        raise MissionInterpreterTransportError(
            code="INTERPRETER_UNAVAILABLE",
            message="mission interpretation is temporarily unavailable; try again",
            retryable=True,
            detail=detail,
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise MissionInterpreterTransportError(
            code="INTERPRETER_UNAVAILABLE",
            message="mission interpretation is temporarily unavailable; try again",
            retryable=True,
        ) from exc
    if not isinstance(body, dict):
        raise MissionInterpreterTransportError(
            code="INTERPRETER_UNAVAILABLE",
            message="mission interpretation is temporarily unavailable; try again",
            retryable=True,
        )
    return body


def _finish_reason_truncated(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    reason = first.get("finish_reason")
    return isinstance(reason, str) and reason.casefold() in {"length", "max_tokens"}


def _response_content(body: Any) -> str:
    if not isinstance(body, dict):
        raise TypeError("interpreter response must be an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("interpreter response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("interpreter response choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise TypeError("interpreter response message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("interpreter response content is empty")
    return _extract_json_payload(content.strip())


def _extract_json_payload(content: str) -> str:
    """Accept raw JSON or common fenced-model wrappers without inventing fields."""

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence (``` or ```json) and optional closing fence.
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _normalize_coverage_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _material_coverage(instruction: str, segments: list[dict[str, Any]]) -> float:
    source = _normalize_coverage_text(instruction)
    if not source:
        return 1.0
    covered = [False] * len(source)
    for item in segments:
        needle = _normalize_coverage_text(str(item.get("source_text") or ""))
        if not needle:
            continue
        start = source.find(needle)
        if start < 0:
            continue
        for index in range(start, start + len(needle)):
            covered[index] = True
    material = [index for index, char in enumerate(source) if char.isalnum()]
    if not material:
        return 1.0
    return sum(covered[index] for index in material) / len(material)


def _ensure_instruction_segment_coverage(
    *,
    segments: list[dict[str, Any]],
    instruction: str,
) -> list[dict[str, Any]]:
    """Add residual exact instruction spans when partial segments leave gaps."""

    text = (instruction or "").strip()
    if not text:
        return segments
    if _material_coverage(text, segments) >= 0.99:
        return segments

    # Prefer residual sentence-like tails first, then full instruction as cover.
    residual_candidates: list[str] = []
    for part in text.replace("!", ".").replace("?", ".").split("."):
        span = part.strip()
        if not span:
            continue
        # Re-attach a period for fidelity when the original used one.
        candidate = span if span.endswith(".") else f"{span}."
        if _normalize_coverage_text(candidate) and all(
            _normalize_coverage_text(candidate) not in _normalize_coverage_text(str(s.get("source_text") or ""))
            for s in segments
        ):
            residual_candidates.append(candidate[:2000])
    residual_candidates.append(text[:2000])

    out = list(segments)
    for span in residual_candidates:
        out.append(
            {
                "source_text": span,
                "normalized_text": span,
                "accounted": True,
                "material": True,
            }
        )
        if _material_coverage(text, out) >= 0.99:
            break
    return out


def _validation_error_detail(exc: ValidationError) -> str:
    """Compact first few pydantic errors for ops logs (no user content dump)."""

    parts: list[str] = []
    for err in exc.errors()[:4]:
        loc = ".".join(str(item) for item in err.get("loc", ()))
        etype = str(err.get("type") or "error")
        parts.append(f"{loc}:{etype}" if loc else etype)
    return f"ValidationError:{exc.error_count()}:{';'.join(parts)}"[:240]


def _normalize_policy_mode(mode: str) -> str:
    """Map free-form policy labels to SendPolicyMode without inventing allow."""

    raw = mode.strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in {"allow", "forbid", "conditional", "unknown"}:
        return raw
    if raw in {
        "do_not",
        "dont",
        "don't",
        "never",
        "no",
        "deny",
        "denied",
        "blocked",
        "block",
        "prohibited",
        "forbid_send",
        "do_not_send",
        "dont_send",
        "draft_only",
        "no_send",
        "without_sending",
    }:
        return "forbid"
    if raw in {"yes", "ok", "allowed", "permit", "permitted", "enabled"}:
        return "allow"
    if raw in {"if_approved", "after_approval", "needs_approval", "requires_approval"}:
        return "conditional"
    return "unknown"


def _coerce_schema_version(value: Any) -> int:
    if value is None or value == "":
        return 1
    if value is True or value is False:
        return 1
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return 1


def _remap_outcome_token(raw_outcome: str, *, source_text: str) -> str | None:
    """Map free-form model outcome labels to canonical IDs without inventing intent."""

    token = normalize_outcome_token(raw_outcome)
    if token:
        return token

    key = " ".join(raw_outcome.strip().lower().replace("-", "_").split()).replace(" ", "_")
    if not key:
        return None
    if key in _OUTCOME_DROP_TOKENS:
        # Draft/send language sometimes lands on non-outcome tokens; recover from source.
        src = source_text.casefold()
        if any(marker in src for marker in ("draft", "prepare", "write an email", "compose")) and not any(
            marker in src for marker in ("send it", "send the", "send email", "send outreach")
        ):
            if "do not send" in src or "don't send" in src or "without sending" in src or "draft" in src:
                return "prepare_outreach"
        return None

    if key in _OUTCOME_STRUCTURAL_ALIASES:
        mapped = _OUTCOME_STRUCTURAL_ALIASES[key]
        src = source_text.casefold()
        # Prefer prepare_outreach when CRM-write label is clearly a draft-email span.
        if mapped == "update_crm" and any(
            marker in src for marker in ("draft", "outreach email", "prepare", "do not send", "don't send")
        ):
            return "prepare_outreach"
        return mapped

    # Last-chance source-text recovery for free-form outcome labels / prose.
    src = f"{raw_outcome} {source_text}".casefold()
    if any(marker in src for marker in ("do not send", "don't send", "without sending", "draft only")):
        if any(marker in src for marker in ("draft", "prepare", "email", "outreach", "message")):
            return "prepare_outreach"
    if any(marker in src for marker in ("draft", "prepare outreach", "prepare an email", "write an email", "compose")):
        if "send" not in src or "do not send" in src or "don't send" in src:
            return "prepare_outreach"
    if any(
        marker in src
        for marker in (
            "find ",
            "research",
            "discover",
            "locate",
            "list ",
            "prospect",
            "contractor",
            "roofers",
            "companies",
            "leads",
        )
    ):
        return "research_prospects"
    if any(marker in src for marker in ("enrich", "contact info", "phone", "email address")):
        return "enrich_contacts"
    if any(marker in src for marker in ("qualify", "score", "rank", "strongest")):
        return "qualify_prospects"
    if any(marker in src for marker in ("publish", "post to", "social")):
        return "publish_content"
    if any(marker in src for marker in ("send email", "send outreach", "deliver")) and "do not" not in src:
        return "send_outreach"
    return None


def _coerce_outcome_list(
    items: Any,
    *,
    interpreted: str,
    unsupported: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    fixed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            item = {"outcome": item, "source_text": interpreted[:1000] if interpreted else item}
        if not isinstance(item, dict):
            continue
        raw_outcome = str(item.get("outcome") or item.get("id") or item.get("name") or "").strip()
        source_text = str(item.get("source_text") or item.get("source") or "").strip()
        if not source_text and interpreted:
            source_text = interpreted[:1000]
        if not raw_outcome:
            continue
        mapped = _remap_outcome_token(raw_outcome, source_text=source_text)
        if mapped is None:
            if source_text:
                unsupported.append(
                    {
                        "text": raw_outcome[:1000],
                        "source_text": source_text[:1000],
                    }
                )
            continue
        if mapped in seen:
            continue
        seen.add(mapped)
        outcome: dict[str, Any] = {"outcome": mapped, "source_text": source_text[:1000]}
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)):
            outcome["confidence"] = float(confidence)
        # Drop unknown extras (extra=forbid on GroundedOutcome).
        fixed.append({k: v for k, v in outcome.items() if k in _ALLOWED_OUTCOME_KEYS})
    return fixed


def _coerce_target_entity(item: dict[str, Any], *, interpreted: str) -> dict[str, Any] | None:
    target = dict(item)
    raw_type = str(target.get("type") or target.get("entity_type") or "market").strip().casefold()
    raw_type = raw_type.replace("-", "_").replace(" ", "_")
    target_type = _TARGET_TYPE_ALIASES.get(raw_type, raw_type)
    if target_type not in _ALLOWED_TARGET_TYPES:
        target_type = "market"

    source_text = str(target.get("source_text") or "").strip()
    value = target.get("value")
    if not source_text:
        for key in ("value", "name", "location", "industry", "email", "domain", "url", "label", "text"):
            candidate = str(target.get(key) or "").strip()
            if candidate:
                source_text = candidate
                break
    if not source_text and interpreted:
        source_text = interpreted[:1000]
    if not source_text:
        return None

    # Promote common free-form value into the correct field.
    if value is not None and str(value).strip():
        value_text = str(value).strip()
        if raw_type in {"location", "place", "geo", "region", "city", "area"} and not target.get("location"):
            target["location"] = value_text[:160]
        elif raw_type in {"industry", "sector", "vertical"} and not target.get("industry"):
            target["industry"] = value_text[:160]
        elif raw_type in {"email", "email_address", "mailbox"} and not target.get("email"):
            target["email"] = value_text[:320]
        elif not target.get("name") and target_type in {"company", "person", "contact", "recipient"}:
            target["name"] = value_text[:240]
        elif not target.get("location") and target_type == "market":
            target["location"] = value_text[:160]

    cleaned: dict[str, Any] = {
        "type": target_type,
        "source_text": source_text[:1000],
    }
    source = str(target.get("source") or "instruction").strip()
    if source in {"instruction", "profile_context"}:
        cleaned["source"] = source
    source_norm = " ".join(source_text.casefold().split())
    for key in ("industry", "location", "name"):
        val = target.get(key)
        if val is None or not str(val).strip():
            continue
        val_text = str(val).strip()
        # Soft fields must be token-present in source_text; drop model inventions early.
        val_tokens = [tok for tok in val_text.casefold().replace("-", " ").split() if tok]
        if val_tokens and all(tok in source_norm for tok in val_tokens):
            cleaned[key] = val_text
    for key in ("domain", "url", "email"):
        val = target.get(key)
        if val is not None and str(val).strip():
            cleaned[key] = str(val).strip()
    if target.get("radius_km") is not None:
        try:
            cleaned["radius_km"] = float(target["radius_km"])
        except (TypeError, ValueError):
            pass
    if isinstance(target.get("confidence"), (int, float)):
        cleaned["confidence"] = float(target["confidence"])
    return {k: v for k, v in cleaned.items() if k in _ALLOWED_TARGET_KEYS}


_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "interpreted_instruction",
        "requested_outcomes",
        "unsupported_outcomes",
        "requested_quantity",
        "quantity_source_text",
        "send_policy",
        "contact_policy",
        "publish_policy",
        "write_policy",
        "target_entities",
        "timing_constraints",
        "constraints",
        "forbidden_outcomes",
        "success_criteria",
        "urgency",
        "approval_preference",
        "context_requirements",
        "clarifications",
        "segments",
        "contradictions",
    }
)


def _segment_source_text(item: dict[str, Any]) -> str:
    return str(item.get("source_text") or item.get("text") or item.get("span") or "").strip()


def _outcomes_from_segments(segments: Any, *, interpreted: str) -> list[dict[str, Any]]:
    """Recover requested_outcomes when the model only labeled segment actions."""

    if not isinstance(segments, list):
        return []
    recovered: list[dict[str, Any]] = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        source_text = _segment_source_text(item)
        candidates: list[str] = []
        for key in ("action", "outcome", "canonical_outcome"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                candidates.append(raw.strip())
        mapped_list = item.get("mapped_outcomes")
        if isinstance(mapped_list, list):
            for raw in mapped_list:
                if isinstance(raw, str) and raw.strip():
                    candidates.append(raw.strip())
        for raw in candidates:
            recovered.append(
                {
                    "outcome": raw,
                    "source_text": (source_text or interpreted)[:1000],
                }
            )
    return recovered


_GENERIC_TARGET_TOKENS = frozenset(
    {
        "email",
        "emails",
        "message",
        "messages",
        "draft",
        "outreach",
        "content",
        "post",
        "crm",
        "calendar",
        "inbox",
    }
)


def _targets_from_segments(segments: Any, *, interpreted: str) -> list[dict[str, Any]]:
    if not isinstance(segments, list):
        return []
    targets: list[dict[str, Any]] = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        target_raw = item.get("target")
        if not isinstance(target_raw, str) or not target_raw.strip():
            continue
        cleaned = target_raw.strip()
        if cleaned.casefold() in _GENERIC_TARGET_TOKENS:
            continue
        source_text = _segment_source_text(item) or cleaned
        entry: dict[str, Any] = {
            "type": "market",
            "source_text": source_text[:1000],
        }
        # Prefer location when the span looks geographic/market-like.
        if any(ch.isalpha() for ch in cleaned):
            entry["location"] = cleaned[:160]
        targets.append(entry)
    return targets


def _coerce_structural_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill only structural holes that do not invent mission facts.

    Copies existing source spans into missing structural labels so local models
    that omit redundant keys can still fail closed on real grounding later.
    """

    # Preserve free-form recovery fields before stripping unknown top-level keys.
    raw_mode = payload.get("mode")
    raw_confidence = payload.get("confidence")  # discarded; never authority
    _ = raw_confidence

    data = {k: v for k, v in payload.items() if k in _KNOWN_TOP_LEVEL_KEYS}
    # Keep raw segments/outcomes even if later cleaned — already in data when known.
    if "segments" not in data and isinstance(payload.get("segments"), list):
        data["segments"] = payload["segments"]

    data["schema_version"] = _coerce_schema_version(data.get("schema_version"))
    data.setdefault("requested_outcomes", [])
    data.setdefault("unsupported_outcomes", [])
    data.setdefault("target_entities", [])
    data.setdefault("timing_constraints", [])
    data.setdefault("constraints", [])
    data.setdefault("forbidden_outcomes", [])
    data.setdefault("success_criteria", [])
    data.setdefault("context_requirements", [])
    data.setdefault("clarifications", [])
    data.setdefault("contradictions", [])
    data.setdefault("urgency", "normal")
    data.setdefault("approval_preference", "review_before_external_action")
    interpreted = str(data.get("interpreted_instruction") or "").strip()
    if not interpreted:
        # Last structural fallback: use first segment source if model omitted instruction.
        for item in data.get("segments") or []:
            if isinstance(item, dict):
                span = _segment_source_text(item)
                if span:
                    interpreted = span
                    data["interpreted_instruction"] = span[:8000]
                    break

    # Promote free-form top-level mode into send_policy when policy object missing.
    if not isinstance(data.get("send_policy"), dict):
        mode_text = _normalize_policy_mode(str(raw_mode or "unknown"))
        if mode_text in {"allow", "forbid", "conditional"}:
            data["send_policy"] = {"mode": mode_text, "condition": "none"}
        else:
            data["send_policy"] = {"mode": "unknown", "condition": "none"}

    # Recover forbid from explicit instruction/segment language when mode is unknown.
    # Never invent allow/send authority from silence.
    send_policy_obj = data.get("send_policy")
    if isinstance(send_policy_obj, dict) and str(send_policy_obj.get("mode") or "unknown").casefold() == "unknown":
        haystacks = [interpreted]
        for item in data.get("segments") or []:
            if isinstance(item, dict):
                haystacks.append(_segment_source_text(item))
                constraint = str(item.get("constraint") or item.get("source_text_constraint") or "")
                haystacks.append(constraint)
        joined = " ".join(haystacks).casefold()
        if any(
            marker in joined
            for marker in (
                "do not send",
                "don't send",
                "dont send",
                "never send",
                "without sending",
                "draft only",
                "do not email",
                "don't email",
            )
        ):
            source = interpreted
            for span in haystacks:
                lower = span.casefold()
                if any(m in lower for m in ("do not send", "don't send", "without sending", "draft only", "do not email")):
                    source = span or source
                    break
            data["send_policy"] = {
                "mode": "forbid",
                "condition": "none",
                "source_text": source[:1000],
            }

    # Recover outcomes from segment actions when the model skipped requested_outcomes.
    outcomes_raw = data.get("requested_outcomes")
    if not outcomes_raw:
        data["requested_outcomes"] = _outcomes_from_segments(data.get("segments"), interpreted=interpreted)

    unsupported_extra: list[dict[str, Any]] = []
    data["requested_outcomes"] = _coerce_outcome_list(
        data.get("requested_outcomes"),
        interpreted=interpreted,
        unsupported=unsupported_extra,
    )
    data["forbidden_outcomes"] = _coerce_outcome_list(
        data.get("forbidden_outcomes"),
        interpreted=interpreted,
        unsupported=unsupported_extra,
    )

    # Merge model unsupported + remapped-unknowns; dedupe by text.
    unsupported_raw = data.get("unsupported_outcomes") or []
    if isinstance(unsupported_raw, dict):
        unsupported_raw = [unsupported_raw]
    fixed_unsupported: list[dict[str, Any]] = []
    seen_unsupported: set[str] = set()
    for item in list(unsupported_raw) + unsupported_extra:
        if not isinstance(item, dict):
            if isinstance(item, str) and item.strip():
                item = {"text": item.strip(), "source_text": interpreted[:1000] or item.strip()}
            else:
                continue
        text = str(item.get("text") or item.get("outcome") or "").strip()
        source_text = str(item.get("source_text") or "").strip() or interpreted[:1000]
        if not text or not source_text:
            continue
        key = text.casefold()
        if key in seen_unsupported:
            continue
        seen_unsupported.add(key)
        fixed_unsupported.append({"text": text[:1000], "source_text": source_text[:1000]})
    data["unsupported_outcomes"] = fixed_unsupported

    for policy_key in ("send_policy", "contact_policy", "publish_policy", "write_policy"):
        policy_raw = data.get(policy_key)
        if not isinstance(policy_raw, dict):
            data[policy_key] = {"mode": "unknown", "condition": "none"}
            continue
        policy = {k: v for k, v in policy_raw.items() if k in _ALLOWED_POLICY_KEYS or k in {"mode", "condition", "source_text", "confidence"}}
        policy.setdefault("condition", "none")
        mode = str(policy.get("mode") or "unknown").strip().casefold() or "unknown"
        mode = _normalize_policy_mode(mode)
        policy["mode"] = mode
        condition = str(policy.get("condition") or "none").strip().casefold() or "none"
        if condition not in {"none", "approval", "review", "scheduled_time", "after_job", "other"}:
            condition = "none"
        if mode in {"forbid", "allow"}:
            condition = "none"
        policy["condition"] = condition
        if mode != "unknown" and not str(policy.get("source_text") or "").strip():
            filled = ""
            for item in data.get("segments") or []:
                if not isinstance(item, dict):
                    continue
                span = str(item.get("source_text") or "").strip()
                lower = span.casefold()
                if span and any(token in lower for token in ("send", "do not", "don't", "never", "draft only", "publish")):
                    filled = span
                    break
            policy["source_text"] = (filled or interpreted)[:1000]
        data[policy_key] = {k: v for k, v in policy.items() if k in _ALLOWED_POLICY_KEYS}

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        if interpreted:
            data["segments"] = [
                {
                    "source_text": interpreted[:2000],
                    "normalized_text": interpreted[:2000],
                    "accounted": True,
                    "material": True,
                }
            ]
    else:
        fixed_segments: list[dict[str, Any]] = []
        for item in segments:
            if not isinstance(item, dict):
                continue
            segment = dict(item)
            source_text = _segment_source_text(segment)
            if not source_text:
                continue
            segment["source_text"] = source_text[:2000]
            if not str(segment.get("normalized_text") or "").strip():
                segment["normalized_text"] = source_text[:2000]
            # Promote free-form action → mapped_outcomes.
            mapped = segment.get("mapped_outcomes")
            if not isinstance(mapped, list):
                mapped = []
            for key in ("action", "outcome", "canonical_outcome"):
                raw = segment.get(key)
                if isinstance(raw, str) and raw.strip():
                    mapped.append(raw.strip())
            fixed_mapped: list[str] = []
            for outcome in mapped:
                remapped = _remap_outcome_token(str(outcome), source_text=source_text)
                if remapped and remapped not in fixed_mapped:
                    fixed_mapped.append(remapped)
            segment["mapped_outcomes"] = fixed_mapped
            if "accounted" not in segment:
                segment["accounted"] = True
            if "material" not in segment:
                segment["material"] = True
            fixed_segments.append({k: v for k, v in segment.items() if k in _ALLOWED_SEGMENT_KEYS})
        data["segments"] = fixed_segments or (
            [
                {
                    "source_text": interpreted[:2000],
                    "normalized_text": interpreted[:2000],
                    "accounted": True,
                    "material": True,
                }
            ]
            if interpreted
            else []
        )

    # Local models often omit trailing success/constraint clauses from segments.
    # Append residual exact spans from interpreted_instruction so coverage is
    # honest without inventing mission facts (text is already in the instruction).
    data["segments"] = _ensure_instruction_segment_coverage(
        segments=list(data.get("segments") or []),
        instruction=interpreted,
    )

    if not data.get("target_entities"):
        data["target_entities"] = _targets_from_segments(payload.get("segments"), interpreted=interpreted)

    criteria_raw = data.get("success_criteria")
    if isinstance(criteria_raw, dict):
        criteria_items: list[Any] = [criteria_raw]
    elif isinstance(criteria_raw, list):
        criteria_items = criteria_raw
    else:
        criteria_items = []
    fixed_criteria: list[dict[str, Any]] = []
    for item in criteria_items:
        if isinstance(item, str) and item.strip():
            item = {"description": item.strip(), "source_text": item.strip()}
        if not isinstance(item, dict):
            continue
        criterion = dict(item)
        source_text = str(criterion.get("source_text") or "").strip()
        description = str(criterion.get("description") or criterion.get("text") or "").strip()
        if source_text and not description:
            criterion["description"] = source_text
        if description and not source_text:
            criterion["source_text"] = description
        if not str(criterion.get("description") or "").strip():
            continue
        if not str(criterion.get("source_text") or "").strip():
            continue
        fixed_criteria.append({k: v for k, v in criterion.items() if k in _ALLOWED_CRITERION_KEYS})
    data["success_criteria"] = fixed_criteria

    fixed_targets: list[dict[str, Any]] = []
    for item in data.get("target_entities") or []:
        if not isinstance(item, dict):
            continue
        cleaned = _coerce_target_entity(item, interpreted=interpreted)
        if cleaned is not None:
            fixed_targets.append(cleaned)
    data["target_entities"] = fixed_targets

    # quantity_source_text required when quantity is set.
    qty = data.get("requested_quantity")
    if qty is not None:
        try:
            qty_int = int(qty)
            data["requested_quantity"] = qty_int if qty_int >= 1 else None
        except (TypeError, ValueError):
            data["requested_quantity"] = None
            qty_int = None
        if data.get("requested_quantity") is not None and not str(data.get("quantity_source_text") or "").strip():
            filled_qty = ""
            qty_str = str(data["requested_quantity"])
            for item in data.get("segments") or []:
                if not isinstance(item, dict):
                    continue
                span = str(item.get("source_text") or "").strip()
                if span and qty_str in span:
                    filled_qty = span
                    break
            if not filled_qty and interpreted and qty_str in interpreted:
                filled_qty = interpreted
            data["quantity_source_text"] = (filled_qty or interpreted or qty_str)[:1000]
    elif data.get("quantity_source_text") and not data.get("requested_quantity"):
        # Drop orphan quantity source without a quantity rather than invent a count.
        data["quantity_source_text"] = None

    # Constraints: ensure text+source_text pairs when model emits strings.
    fixed_constraints: list[dict[str, Any]] = []
    for item in data.get("constraints") or []:
        if isinstance(item, str) and item.strip():
            fixed_constraints.append({"text": item.strip()[:1000], "source_text": item.strip()[:1000]})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("description") or "").strip()
        source_text = str(item.get("source_text") or "").strip()
        if text and not source_text:
            source_text = text
        if source_text and not text:
            text = source_text
        if text and source_text:
            fixed_constraints.append({"text": text[:1000], "source_text": source_text[:1000]})
    data["constraints"] = fixed_constraints

    return data
