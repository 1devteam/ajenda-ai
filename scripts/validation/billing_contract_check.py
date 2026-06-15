#!/usr/bin/env python3
"""Billing integration contract sentinel.

Validates that the StripeBillingService contract is coherent with the rest of
the codebase before any CI artefact is produced. Fails fast with a clear
diagnostic if the billing surface drifts from the declared contract.

Checks performed:
  1. StripeBillingService is importable from its declared module path.
  2. The assert_subscription_active method exists and has the expected signature.
  3. All Stripe-related env-var fields declared in Settings are present in the
     k8s secret example manifest so operators are not surprised at deploy time.
  4. The stripe package is declared as a project dependency in pyproject.toml.

Exit codes:
  0 — all checks passed
  1 — one or more checks failed (details printed to stderr)
"""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
SECRET_EXAMPLE = REPO_ROOT / "deploy" / "k8s" / "secret.example.yaml"
CONFIG_MODULE = "backend.app.config"
BILLING_MODULE = "backend.services.billing_stripe_integration"
BILLING_CLASS = "StripeBillingService"
REQUIRED_METHOD = "assert_subscription_active"

# Stripe env-var fields declared in Settings that must appear in the k8s secret example.
REQUIRED_SECRET_KEYS = {
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_STARTER",
    "STRIPE_PRICE_PRO",
}

_errors: list[str] = []


def _fail(msg: str) -> None:
    _errors.append(msg)
    print(f"  FAIL  {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"  OK    {msg}")


# ---------------------------------------------------------------------------
# Check 1: StripeBillingService is importable
# ---------------------------------------------------------------------------
print(f"[billing_contract_check] Importing {BILLING_MODULE} …")
try:
    billing_mod = importlib.import_module(BILLING_MODULE)
    _ok(f"{BILLING_MODULE} imported successfully")
except Exception as exc:  # noqa: BLE001
    _fail(f"Cannot import {BILLING_MODULE}: {exc}")
    billing_mod = None

# ---------------------------------------------------------------------------
# Check 2: assert_subscription_active exists and has expected signature
# ---------------------------------------------------------------------------
if billing_mod is not None:
    cls = getattr(billing_mod, BILLING_CLASS, None)
    if cls is None:
        _fail(f"{BILLING_CLASS} not found in {BILLING_MODULE}")
    else:
        _ok(f"{BILLING_CLASS} class found")
        method = getattr(cls, REQUIRED_METHOD, None)
        if method is None:
            _fail(f"{BILLING_CLASS}.{REQUIRED_METHOD} method is missing")
        else:
            sig = inspect.signature(method)
            params = list(sig.parameters)
            if "tenant_id" not in params:
                _fail(
                    f"{BILLING_CLASS}.{REQUIRED_METHOD} must accept a 'tenant_id' parameter; "
                    f"found: {params}"
                )
            else:
                _ok(f"{BILLING_CLASS}.{REQUIRED_METHOD}(tenant_id=…) signature is correct")

# ---------------------------------------------------------------------------
# Check 3: All Stripe keys present in k8s secret example
# ---------------------------------------------------------------------------
print(f"[billing_contract_check] Checking {SECRET_EXAMPLE.relative_to(REPO_ROOT)} …")
if not SECRET_EXAMPLE.exists():
    _fail(f"Secret example manifest not found: {SECRET_EXAMPLE}")
else:
    secret_text = SECRET_EXAMPLE.read_text(encoding="utf-8")
    for key in sorted(REQUIRED_SECRET_KEYS):
        if key not in secret_text:
            _fail(f"Stripe key '{key}' is missing from {SECRET_EXAMPLE.relative_to(REPO_ROOT)}")
        else:
            _ok(f"Secret manifest contains {key}")

# ---------------------------------------------------------------------------
# Check 4: stripe package declared in pyproject.toml dependencies
# ---------------------------------------------------------------------------
print(f"[billing_contract_check] Checking {PYPROJECT.relative_to(REPO_ROOT)} …")
if not PYPROJECT.exists():
    _fail("pyproject.toml not found at repo root")
else:
    with PYPROJECT.open("rb") as fh:
        pyproject_data = tomllib.load(fh)
    deps: list[str] = pyproject_data.get("project", {}).get("dependencies", [])
    stripe_declared = any(re.match(r"stripe\b", dep) for dep in deps)
    if not stripe_declared:
        _fail("'stripe' package is not declared in [project].dependencies in pyproject.toml")
    else:
        _ok("stripe package declared in pyproject.toml dependencies")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
if _errors:
    print(f"[billing_contract_check] FAILED — {len(_errors)} error(s) detected.", file=sys.stderr)
    sys.exit(1)

print("[billing_contract_check] All checks passed.")
