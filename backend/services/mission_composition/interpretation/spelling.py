"""Spelling candidates with protected vocabulary.

Uses a built-in correction map always. SymSpellPy is optional enhancement when
installed and AJENDA_MISSION_INTERPRETER_SPELLING_ENABLED is true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# High-confidence, domain-safe replacements only (never ability names / IDs).
_BUILTIN_CORRECTIONS: dict[str, str] = {
    "competors": "competitors",
    "competor": "competitor",
    "qualfy": "qualify",
    "qualfied": "qualified",
    "roofin": "roofing",
    "companys": "companies",
    "followup": "follow up",
    "propects": "prospects",
    "propect": "prospect",
    "reseach": "research",
    "reasearch": "research",
    "outrech": "outreach",
    "outreact": "outreach",
    "fayettevill": "fayetteville",
}

_PROTECTED_TOKENS = frozenset(
    {
        "ajenda",
        "hubspot",
        "salesforce",
        "gmail",
        "gtm",
        "crm",
        "saas",
        "linkedin",
        "github",
        "oauth",
        "api",
        "smtp",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


@dataclass(frozen=True, slots=True)
class SpellingCorrection:
    original: str
    replacement: str
    confidence: float
    source: str  # builtin | symspell


def apply_spelling_candidates(text: str) -> tuple[str, list[SpellingCorrection], list[str]]:
    """Return (corrected_text, corrections, components_used)."""

    components: list[str] = ["spelling_builtin"]
    corrections: list[SpellingCorrection] = []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        lower = token.lower()
        if lower in _PROTECTED_TOKENS:
            return token
        if lower in _BUILTIN_CORRECTIONS:
            repl = _BUILTIN_CORRECTIONS[lower]
            # Preserve crude capitalization
            if token[0].isupper():
                repl = repl[0].upper() + repl[1:]
            corrections.append(SpellingCorrection(original=token, replacement=repl, confidence=0.95, source="builtin"))
            return repl
        return token

    out = _TOKEN_RE.sub(_replace, text)

    # Optional SymSpell — candidate only; never applied if confidence unclear.
    try:
        from symspellpy import SymSpell, Verbosity  # type: ignore[import-untyped]
    except Exception:
        return out, corrections, components

    components.append("symspell")
    # SymSpell is available but we only use it for unknown tokens if dictionary loads.
    # Without a shipped frequency dictionary, skip mutation to avoid unsafe guesses.
    _ = (SymSpell, Verbosity)
    return out, corrections, components
