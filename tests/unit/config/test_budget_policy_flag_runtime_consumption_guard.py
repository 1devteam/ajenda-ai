from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
IGNORED_PATH_PREFIXES = (
    ".env",
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "build/",
    "dist/",
    "htmlcov/",
    "__pycache__/",
)
ALLOWED_PATH_PREFIXES = (
    "backend/app/config.py",
    "backend/services/quota_enforcement.py",
    "tests/",
    "docs/",
    "deploy/",
    ".env.example",
)
BUDGET_POLICY_TOKENS = (
    "budget_policy_enabled",
    "budget_policy_observe_only",
    "budget_policy_enforce",
    "AJENDA_BUDGET_POLICY_ENABLED",
    "AJENDA_BUDGET_POLICY_OBSERVE_ONLY",
    "AJENDA_BUDGET_POLICY_ENFORCE",
)


def test_bundle_5_3_budget_policy_flags_only_consumed_by_budget_gate_paths() -> None:
    unexpected: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel == ignored or rel.startswith(ignored) for ignored in IGNORED_PATH_PREFIXES):
            continue
        if any(rel == allowed or rel.startswith(allowed) for allowed in ALLOWED_PATH_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(token in text for token in BUDGET_POLICY_TOKENS):
            unexpected.append(rel)

    assert not unexpected, f"Bundle 5.3 runtime-consumption guard failed; unexpected paths: {sorted(unexpected)}"
