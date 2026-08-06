#!/usr/bin/env python3
"""Insert Wave A action handlers into action_inputs.py before the final return."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
target = root / "backend/services/mission_composition/action_inputs.py"
handlers_path = root / "artifacts/wave-a/action_inputs_handlers_wave_a.txt"
if not target.exists() or not handlers_path.exists():
    sys.exit(f"missing {target} or {handlers_path}")
text = target.read_text()
if "linkedin.profile_read" in text:
    print("already applied")
    sys.exit(0)
handlers = handlers_path.read_text()
marker = '    return {"context": {"objective": intent.objective[:300], "query": query}}'
if marker not in text:
    sys.exit("marker not found in action_inputs.py")
text = text.replace(marker, handlers + "\n" + marker, 1)
target.write_text(text)
assert "linkedin.profile_read" in target.read_text()
assert "github.repo_read" in target.read_text()
assert "people.googleapis.com" in target.read_text()
print(f"OK updated {target}")
