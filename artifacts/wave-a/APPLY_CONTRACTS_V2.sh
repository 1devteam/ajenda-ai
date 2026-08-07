#!/usr/bin/env bash
# APPLY_CONTRACTS_V2.sh — pure Python string replace (no git-apply)
set -euo pipefail
TARGET="${1:-backend/services/mission_composition/contracts.py}"
python3 - "$TARGET" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()

if 'JOB_CATALOG_VERSION = "5"' in text and '"read_linkedin"' in text:
    print("already applied")
    sys.exit(0)

text = text.replace('JOB_CATALOG_VERSION = "4"', 'JOB_CATALOG_VERSION = "5"')
text = text.replace('INTERPRETER_VERSION = "7"', 'INTERPRETER_VERSION = "8"')
text = text.replace('CAPABILITY_RESOLVER_VERSION = "4"', 'CAPABILITY_RESOLVER_VERSION = "5"')

old_lit = '''CanonicalOutcome = Literal[
    "research_prospects",
    "qualify_prospects",
    "enrich_contacts",
    "prepare_outreach",
    "send_outreach",
    "update_crm",
    "publish_content",
    "read_calendar",
    "read_email",
    "read_crm",
    "query_salesforce",
]'''
new_lit = '''CanonicalOutcome = Literal[
    "research_prospects",
    "qualify_prospects",
    "enrich_contacts",
    "prepare_outreach",
    "send_outreach",
    "update_crm",
    "publish_content",
    "read_calendar",
    "read_email",
    "read_crm",
    "query_salesforce",
    "read_linkedin",
    "read_github",
    "read_contacts",
]'''
if old_lit not in text:
    print("ERROR: CanonicalOutcome block not found as expected", file=sys.stderr)
    sys.exit(1)
text = text.replace(old_lit, new_lit)

old_fs = '''CANONICAL_OUTCOMES: frozenset[str] = frozenset(
    {
        "research_prospects",
        "qualify_prospects",
        "enrich_contacts",
        "prepare_outreach",
        "send_outreach",
        "update_crm",
        "publish_content",
        "read_calendar",
        "read_email",
        "read_crm",
        "query_salesforce",
    }
)'''
new_fs = '''CANONICAL_OUTCOMES: frozenset[str] = frozenset(
    {
        "research_prospects",
        "qualify_prospects",
        "enrich_contacts",
        "prepare_outreach",
        "send_outreach",
        "update_crm",
        "publish_content",
        "read_calendar",
        "read_email",
        "read_crm",
        "query_salesforce",
        "read_linkedin",
        "read_github",
        "read_contacts",
    }
)'''
if old_fs not in text:
    print("ERROR: CANONICAL_OUTCOMES block not found", file=sys.stderr)
    sys.exit(1)
text = text.replace(old_fs, new_fs)

old_end = '''    "search salesforce": "query_salesforce",
}'''
new_end = '''    "search salesforce": "query_salesforce",
    "read linkedin": "read_linkedin",
    "linkedin profile": "read_linkedin",
    "my linkedin": "read_linkedin",
    "linkedin profile read": "read_linkedin",
    "check linkedin": "read_linkedin",
    "read github": "read_github",
    "github repo": "read_github",
    "github repository": "read_github",
    "read github repo": "read_github",
    "check github": "read_github",
    "read contacts": "read_contacts",
    "google contacts": "read_contacts",
    "my contacts": "read_contacts",
    "list contacts": "read_contacts",
    "read google contacts": "read_contacts",
    "check contacts": "read_contacts",
}'''
if old_end not in text:
    if '"read linkedin"' in text:
        print("aliases already present")
    else:
        print("ERROR: LEGACY_OUTCOME_ALIASES tail not found", file=sys.stderr)
        sys.exit(1)
else:
    text = text.replace(old_end, new_end)

path.write_text(text)
print("OK contracts Wave A applied")
print("  JOB_CATALOG_VERSION =", "5" if 'JOB_CATALOG_VERSION = "5"' in text else "FAIL")
print("  read_linkedin present =", '"read_linkedin"' in text)
PY
