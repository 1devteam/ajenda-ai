"""Global pytest configuration shared by unit and integration suites.

Ensures the repository root is importable so tests can import ``backend``
without requiring an editable package install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
