#!/usr/bin/env python3
"""Apply Wave A operator-read patterns to intent_interpreter.py."""
from __future__ import annotations

from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
target = root / "backend/services/mission_composition/intent_interpreter.py"
text = target.read_text()
if "_LINKEDIN_READ_PATTERNS" in text and "wants_linkedin_read" in text:
    print("already applied")
    sys.exit(0)

PATTERNS = r'''
# Wave A operator reads — distinct from publish (LinkedIn) and CRM write (contacts).
_LINKEDIN_READ_PATTERNS = (
    r"\b(?:check|read|show|fetch|get|open)\b.{0,40}\blinkedin\b.{0,24}\bprofile\b",
    r"\blinkedin\b.{0,24}\bprofile\b",
    r"\b(?:my|the)\s+linkedin\s+profile\b",
    r"\bread\s+(?:my\s+)?linkedin\b",
)
_GITHUB_READ_PATTERNS = (
    r"\b(?:check|read|show|fetch|get|open)\b.{0,40}\bgithub\b.{0,40}\b(?:repo|repository)\b",
    r"\bgithub\b.{0,24}\b(?:repo|repository)\b",
    r"\bread\s+(?:the\s+)?github\b",
    r"\bgithub\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b",
)
_CONTACTS_READ_PATTERNS = (
    r"\b(?:check|read|list|show|fetch|get)\b.{0,40}\bgoogle\s+contacts?\b",
    r"\bgoogle\s+contacts?\b",
    r"\b(?:check|read|list|show)\b.{0,24}\b(?:my\s+)?contacts?\b",
    r"\b(?:my|the)\s+(?:google\s+)?contacts?\b",
)
'''

marker_pat = "_HUBSPOT_COMPANY_AFTER = re.compile("
if marker_pat not in text:
    sys.exit("pattern insert marker not found")
if "_LINKEDIN_READ_PATTERNS" not in text:
    text = text.replace(marker_pat, PATTERNS + "\n" + marker_pat, 1)

wants_block = """    # Wave A operator reads — fail closed against publish/write collisions.
    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish
    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)
    wants_contacts_read = _contains_any(lower, _CONTACTS_READ_PATTERNS) and not wants_crm

"""
marker_wants = "    outcomes: list[CanonicalOutcome] = []"
if "wants_linkedin_read" not in text:
    if marker_wants not in text:
        sys.exit("wants insert marker not found")
    text = text.replace(marker_wants, wants_block + marker_wants, 1)

outcomes_block = """    if wants_linkedin_read and \"read_linkedin\" not in outcomes:
        outcomes.append(\"read_linkedin\")
        evidence.append(
            _evidence(
                field_path=\"requested_outcomes.read_linkedin\",
                source=\"explicit\",
                normalized_value=\"read_linkedin\",
                confidence=0.95,
                rule_id=\"connector.linkedin_profile_read\",
            )
        )
    if wants_github_read and \"read_github\" not in outcomes:
        outcomes.append(\"read_github\")
        evidence.append(
            _evidence(
                field_path=\"requested_outcomes.read_github\",
                source=\"explicit\",
                normalized_value=\"read_github\",
                confidence=0.95,
                rule_id=\"connector.github_repo_read\",
            )
        )
    if wants_contacts_read and \"read_contacts\" not in outcomes:
        outcomes.append(\"read_contacts\")
        evidence.append(
            _evidence(
                field_path=\"requested_outcomes.read_contacts\",
                source=\"explicit\",
                normalized_value=\"read_contacts\",
                confidence=0.95,
                rule_id=\"connector.google_contacts_read\",
            )
        )
"""

if "wants_linkedin_read and" not in text:
    idx = text.find("    if wants_calendar:")
    if idx < 0:
        sys.exit("calendar outcome marker not found")
    rest = text[idx:]
    end_rel = rest.find("\n    if wants_crm:")
    if end_rel < 0:
        end_rel = rest.find("\n    if wants_publish:")
    if end_rel < 0:
        sys.exit("could not find insertion point after calendar")
    insert_at = idx + end_rel
    text = text[:insert_at] + "\n" + outcomes_block + text[insert_at:]

success_block = """    if \"read_linkedin\" in outcomes:
        success.append(
            SuccessCriterion(
                description=\"LinkedIn profile fields are returned with provider evidence\",
                measurable=True,
            )
        )
    if \"read_github\" in outcomes:
        success.append(
            SuccessCriterion(
                description=\"GitHub repository metadata is returned with provider evidence\",
                measurable=True,
            )
        )
    if \"read_contacts\" in outcomes:
        success.append(
            SuccessCriterion(
                description=\"Google Contacts records are returned with provider evidence\",
                measurable=True,
            )
        )
"""
if "LinkedIn profile fields" not in text:
    marker_success = '    if "publish_content" in outcomes:'
    if marker_success in text:
        text = text.replace(marker_success, success_block + "\n" + marker_success, 1)

target.write_text(text)
final = target.read_text()
assert "_LINKEDIN_READ_PATTERNS" in final
assert "wants_linkedin_read" in final
assert "read_linkedin" in final
print(f"OK updated {target} ({target.stat().st_size} bytes)")
