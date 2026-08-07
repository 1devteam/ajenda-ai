#!/usr/bin/env python3
"""Surgical Wave A install for intent_interpreter.py — complete, idempotent.

Fixes incomplete prior install that added outcome appends without:
  - pattern constants (_LINKEDIN_READ_PATTERNS, etc.)
  - wants_* variable definitions
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/services/mission_composition/intent_interpreter.py")

PATTERNS_BLOCK = '''
_LINKEDIN_READ_PATTERNS = (
    r"\\b(?:check|read|show|fetch|get|open)\\b.{0,40}\\blinkedin\\b.{0,24}\\bprofile\\b",
    r"\\blinkedin\\b.{0,24}\\bprofile\\b",
    r"\\b(?:my|the)\\s+linkedin\\s+profile\\b",
    r"\\bread\\s+(?:my\\s+)?linkedin\\b",
)
_GITHUB_READ_PATTERNS = (
    r"\\b(?:check|read|show|fetch|get|open)\\b.{0,40}\\bgithub\\b.{0,40}\\b(?:repo|repository)\\b",
    r"\\bgithub\\b.{0,24}\\b(?:repo|repository)\\b",
    r"\\bread\\s+(?:the\\s+)?github\\b",
    r"\\bgithub\\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\\b",
)
_CONTACTS_READ_PATTERNS = (
    r"\\b(?:check|read|list|show|fetch|get)\\b.{0,40}\\bgoogle\\s+contacts?\\b",
    r"\\bgoogle\\s+contacts?\\b",
    r"\\b(?:check|read|list|show)\\b.{0,24}\\b(?:my\\s+)?contacts?\\b",
    r"\\b(?:my|the)\\s+(?:google\\s+)?contacts?\\b",
)
'''

WANTS_BLOCK = '''    # Wave A operator reads — fail closed against publish/write collisions.
    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish
    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)
    wants_contacts_read = _contains_any(lower, _CONTACTS_READ_PATTERNS) and not wants_crm
'''

OUTCOMES_BLOCK = '''    if wants_linkedin_read and "read_linkedin" not in outcomes:
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
'''


def main() -> None:
    text = TARGET.read_text()
    changed = False

    # 1) Pattern constants
    if "_LINKEDIN_READ_PATTERNS" not in text:
        anchor = "_HUBSPOT_COMPANY_AFTER"
        if anchor in text:
            text = text.replace(anchor, PATTERNS_BLOCK.strip() + "\n" + anchor, 1)
            changed = True
            print("+ inserted _LINKEDIN/_GITHUB/_CONTACTS_READ_PATTERNS")
        else:
            print("ERROR: cannot find insertion point for patterns", file=sys.stderr)
            sys.exit(1)
    else:
        print("= patterns already present")

    # 2) wants_* definitions
    if "wants_linkedin_read =" not in text:
        markers = [
            "    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None\n",
            "    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None\r\n",
        ]
        inserted = False
        for m in markers:
            if m in text:
                text = text.replace(m, m + WANTS_BLOCK, 1)
                inserted = True
                changed = True
                print("+ inserted wants_linkedin_read / wants_github_read / wants_contacts_read")
                break
        if not inserted:
            if "wants_publish = _contains_any(lower, _PUBLISH_PATTERNS)" in text:
                idx = text.find("wants_publish = _contains_any(lower, _PUBLISH_PATTERNS)")
                rest = text[idx:]
                end = rest.find("\n    outcomes:")
                if end == -1:
                    end = rest.find("\n    outcomes :")
                if end != -1:
                    insert_at = idx + end
                    text = text[:insert_at] + "\n" + WANTS_BLOCK + text[insert_at:]
                    inserted = True
                    changed = True
                    print("+ inserted wants_* before outcomes:")
            if not inserted:
                print("ERROR: cannot find insertion point for wants_*", file=sys.stderr)
                sys.exit(1)
    else:
        print("= wants_* already present")

    # 3) Outcome appends
    if 'rule_id="connector.linkedin_profile_read"' not in text:
        anchors = [
            '    if wants_calendar:\n        outcomes.append("read_calendar")\n',
            '    if wants_calendar:\n        outcomes.append("read_calendar")\r\n',
        ]
        inserted = False
        for a in anchors:
            if a in text:
                text = text.replace(a, a + OUTCOMES_BLOCK, 1)
                inserted = True
                changed = True
                print("+ inserted read_linkedin/github/contacts outcome blocks")
                break
        if not inserted and "if wants_linkedin_read" in text:
            print("= outcome refs present but evidence block missing — manual check needed")
        elif not inserted:
            print("ERROR: cannot find insertion point for outcome blocks", file=sys.stderr)
            sys.exit(1)
    else:
        print("= outcome blocks already present")

    if changed:
        TARGET.write_text(text)
        print(f"OK wrote {TARGET}")
    else:
        print("OK no changes needed")

    final = TARGET.read_text()
    checks = [
        ("_LINKEDIN_READ_PATTERNS", "_LINKEDIN_READ_PATTERNS" in final),
        ("wants_linkedin_read =", "wants_linkedin_read =" in final),
        ("wants_github_read =", "wants_github_read =" in final),
        ("wants_contacts_read =", "wants_contacts_read =" in final),
        ("read_linkedin outcome", 'outcomes.append("read_linkedin")' in final),
    ]
    for name, ok in checks:
        print(f"  {'OK' if ok else 'FAIL'} {name}")
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
