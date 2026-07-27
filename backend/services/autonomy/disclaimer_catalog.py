from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

CATALOG_PATH = Path(__file__).resolve().parents[3] / "docs" / "product" / "autonomy-disclaimer-catalog.v1.yaml"


class AutonomyPolicyError(ValueError):
    """Deterministic informed-autonomy validation failure."""


@dataclass(frozen=True, slots=True)
class DisclaimerEntry:
    disclaimer_id: str
    tier: int
    actions: tuple[str, ...]
    text: str
    text_hash: str


@dataclass(frozen=True, slots=True)
class AutonomyAcknowledgment:
    schema_version: int
    disclaimer_id: str
    disclaimer_text_hash: str
    accepted_at: str
    principal_id: str
    action: str
    side_effect_class: str | None = None


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _hash_text(text: str) -> str:
    normalized = _normalize_text(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@lru_cache(maxsize=1)
def load_disclaimer_catalog() -> tuple[DisclaimerEntry, ...]:
    if not CATALOG_PATH.is_file():
        raise AutonomyPolicyError(f"disclaimer catalog not found: {CATALOG_PATH}")
    loaded = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AutonomyPolicyError("disclaimer catalog must be a mapping")
    raw_entries = loaded.get("disclaimers")
    if not isinstance(raw_entries, list):
        raise AutonomyPolicyError("disclaimer catalog missing disclaimers list")

    entries: list[DisclaimerEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            raise AutonomyPolicyError("disclaimer entry must be a mapping")
        disclaimer_id = str(item.get("disclaimer_id", "")).strip()
        tier = item.get("tier")
        actions_raw = item.get("actions")
        text = item.get("text")
        if not disclaimer_id:
            raise AutonomyPolicyError("disclaimer entry missing disclaimer_id")
        if not isinstance(tier, int):
            raise AutonomyPolicyError(f"disclaimer {disclaimer_id} missing integer tier")
        if not isinstance(actions_raw, list) or not actions_raw:
            raise AutonomyPolicyError(f"disclaimer {disclaimer_id} missing actions")
        if not isinstance(text, str) or not text.strip():
            raise AutonomyPolicyError(f"disclaimer {disclaimer_id} missing text")
        normalized_text = _normalize_text(text)
        entries.append(
            DisclaimerEntry(
                disclaimer_id=disclaimer_id,
                tier=tier,
                actions=tuple(str(action) for action in actions_raw),
                text=normalized_text,
                text_hash=_hash_text(normalized_text),
            )
        )
    return tuple(entries)


def disclaimer_for_action(action_name: str) -> DisclaimerEntry | None:
    for entry in load_disclaimer_catalog():
        if action_name in entry.actions:
            return entry
    return None


def action_tier(action_name: str) -> int:
    entry = disclaimer_for_action(action_name)
    if entry is not None:
        return entry.tier
    if action_name in {
        "calendar.read",
        "sales.qualify",
        "sales.score_lead",
        "sales.recommend_next_action",
        "record.search",
        "record.read",
        "gtm.lead_enrich",
        "retrieval.hybrid_search",
        "web.research",
    }:
        return 0
    if action_name in {"web.search", "web.page_read", "web.browser_session", "http.request"}:
        return 2
    if action_name in {"web.open_write"}:
        return 3
    return 0


def parse_autonomy_acknowledgment(raw: Any) -> AutonomyAcknowledgment:
    if not isinstance(raw, dict):
        raise AutonomyPolicyError("autonomy_acknowledgment must be an object")
    try:
        schema_version = int(raw.get("schema_version", 0))
    except (TypeError, ValueError) as exc:
        raise AutonomyPolicyError("autonomy_acknowledgment.schema_version must be an integer") from exc
    if schema_version != 1:
        raise AutonomyPolicyError("autonomy_acknowledgment.schema_version must be 1")
    for field in ("disclaimer_id", "disclaimer_text_hash", "accepted_at", "principal_id", "action"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AutonomyPolicyError(f"autonomy_acknowledgment.{field} is required")
    side_effect_class = raw.get("side_effect_class")
    if side_effect_class is not None and (not isinstance(side_effect_class, str) or not side_effect_class.strip()):
        raise AutonomyPolicyError("autonomy_acknowledgment.side_effect_class must be a non-empty string when set")
    return AutonomyAcknowledgment(
        schema_version=schema_version,
        disclaimer_id=raw["disclaimer_id"].strip(),
        disclaimer_text_hash=raw["disclaimer_text_hash"].strip(),
        accepted_at=raw["accepted_at"].strip(),
        principal_id=raw["principal_id"].strip(),
        action=raw["action"].strip(),
        side_effect_class=side_effect_class.strip() if isinstance(side_effect_class, str) else None,
    )


def validate_autonomy_acknowledgment(*, acknowledgment: AutonomyAcknowledgment, action_name: str) -> DisclaimerEntry:
    if acknowledgment.action != action_name:
        raise AutonomyPolicyError("autonomy_acknowledgment.action must match launch action")
    entry = disclaimer_for_action(action_name)
    if entry is None:
        raise AutonomyPolicyError(f"no disclaimer catalog entry for action {action_name}")
    if acknowledgment.disclaimer_id != entry.disclaimer_id:
        raise AutonomyPolicyError("autonomy_acknowledgment.disclaimer_id does not match action tier")
    if acknowledgment.disclaimer_text_hash != entry.text_hash:
        raise AutonomyPolicyError("autonomy_acknowledgment.disclaimer_text_hash mismatch")
    return entry


def catalog_entries_for_api() -> list[dict[str, Any]]:
    return [
        {
            "disclaimer_id": entry.disclaimer_id,
            "tier": entry.tier,
            "actions": list(entry.actions),
            "text": entry.text,
            "text_hash": entry.text_hash,
        }
        for entry in load_disclaimer_catalog()
    ]
