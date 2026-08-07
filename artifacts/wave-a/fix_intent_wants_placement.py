#!/usr/bin/env python3
"""Fix misplaced Wave A wants_* in intent_interpreter.py.

Bug: wants_* was inserted into _classify_clause (where wants_publish/wants_crm
are undefined). Outcome appends in interpret_instruction then NameError.

Correct:
  - interpret_instruction: define wants_* after publish_result_based
  - _classify_clause: use pattern checks directly (no wants_* vars)
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/services/mission_composition/intent_interpreter.py")

BAD_IN_CLASSIFY = '''    lower = clause.lower()
    # Wave A operator reads — fail closed against publish/write collisions.
    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish
    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)
    wants_contacts_read = _contains_any(lower, _CONTACTS_READ_PATTERNS) and not wants_crm

    outcomes: list[CanonicalOutcome] = []
'''

GOOD_CLASSIFY_START = '''    lower = clause.lower()
    outcomes: list[CanonicalOutcome] = []
'''

CLASSIFY_WAVE_A = '''    if salesforce_query:
        outcomes.append("query_salesforce")
    # Wave A operator reads (before write/publish so "linkedin profile" is not publish).
    if _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not _contains_any(lower, _PUBLISH_PATTERNS):
        outcomes.append("read_linkedin")
    if _contains_any(lower, _GITHUB_READ_PATTERNS):
        outcomes.append("read_github")
    # Contacts read only when not a CRM write ("add/save to contacts").
    if _contains_any(lower, _CONTACTS_READ_PATTERNS) and not _contains_any(lower, _CRM_UPDATE_PATTERNS):
        outcomes.append("read_contacts")
    if _contains_any(lower, _DRAFT_PATTERNS):
'''

CLASSIFY_ANCHOR_OLD = '''    if salesforce_query:
        outcomes.append("query_salesforce")
    if _contains_any(lower, _DRAFT_PATTERNS):
'''

WANTS_IN_INTERPRET = '''    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None
    # Wave A operator reads — fail closed against publish/write collisions.
    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish
    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)
    wants_contacts_read = _contains_any(lower, _CONTACTS_READ_PATTERNS) and not wants_crm

'''

PUBLISH_ONLY = '''    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None

'''


def main() -> None:
    text = TARGET.read_text()
    changed = False

    if BAD_IN_CLASSIFY in text:
        text = text.replace(BAD_IN_CLASSIFY, GOOD_CLASSIFY_START, 1)
        changed = True
        print("+ removed bad wants_* from _classify_clause")
    else:
        print("= no bad wants_* block in _classify_clause (or already fixed)")

    if 'outcomes.append("read_linkedin")' not in text.split("def interpret_instruction")[0]:
        if CLASSIFY_ANCHOR_OLD in text:
            text = text.replace(CLASSIFY_ANCHOR_OLD, CLASSIFY_WAVE_A, 1)
            changed = True
            print("+ inserted Wave A reads into _classify_clause")
        else:
            print("! could not find classify anchor for Wave A reads — check manually")
    else:
        print("= _classify_clause already maps read_linkedin")

    if "wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS)" not in text.split("def interpret_instruction")[1]:
        if PUBLISH_ONLY in text:
            text = text.replace(PUBLISH_ONLY, WANTS_IN_INTERPRET, 1)
            changed = True
            print("+ inserted wants_* into interpret_instruction")
        elif "publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None" in text:
            parts = text.split("def interpret_instruction", 1)
            head, tail = parts[0], parts[1]
            marker = "    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None\n"
            if marker in tail and "wants_linkedin_read =" not in tail.split("outcomes: list[CanonicalOutcome]")[0]:
                tail = tail.replace(
                    marker,
                    "    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None\n"
                    "    # Wave A operator reads — fail closed against publish/write collisions.\n"
                    "    wants_linkedin_read = _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not wants_publish\n"
                    "    wants_github_read = _contains_any(lower, _GITHUB_READ_PATTERNS)\n"
                    "    wants_contacts_read = _contains_any(lower, _CONTACTS_READ_PATTERNS) and not wants_crm\n",
                    1,
                )
                text = head + "def interpret_instruction" + tail
                changed = True
                print("+ inserted wants_* into interpret_instruction (split path)")
            else:
                print("! wants_* still missing and marker path failed")
        else:
            print("ERROR: publish_result_based not found", file=sys.stderr)
            sys.exit(1)
    else:
        print("= interpret_instruction already has wants_*")

    if changed:
        TARGET.write_text(text)
        print(f"OK wrote {TARGET}")
    else:
        print("OK no file changes")

    final = TARGET.read_text()
    interpret_body = final.split("def interpret_instruction", 1)[1]
    classify_body = final.split("def _classify_clause", 1)[1].split("def interpret_instruction", 1)[0]
    checks = [
        ("interpret wants_linkedin_read =", "wants_linkedin_read = _contains_any" in interpret_body),
        ("interpret uses wants_linkedin_read", "if wants_linkedin_read" in interpret_body),
        ("classify has no wants_publish ref", "not wants_publish" not in classify_body),
        ("classify maps read_linkedin", 'outcomes.append("read_linkedin")' in classify_body),
        ("patterns present", "_LINKEDIN_READ_PATTERNS" in final),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'OK' if passed else 'FAIL'} {name}")
        if not passed:
            ok = False
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
