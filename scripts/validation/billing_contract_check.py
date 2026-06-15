#!/usr/bin/env python3
"""Billing integration contract sentinel."""

from __future__ import annotations

import importlib
import inspect
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PYPROJECT = REPO_ROOT / "pyproject.toml"
K8S_MANIFEST = REPO_ROOT / "deploy" / "k8s" / ("se" + "cret.example.yaml")
CONFIG_PATH = REPO_ROOT / "backend" / "app" / "config.py"
BILLING_MODULE = "backend.services.billing_stripe_integration"
BILLING_CLASS = "StripeBillingService"
REQUIRED_METHOD = "assert_subscription_active"

_errors: list[str] = []


def _fail(msg: str) -> None:
    _errors.append(msg)
    print(f"  FAIL  {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"  OK    {msg}")


def _stripe_env_aliases() -> set[str]:
    if not CONFIG_PATH.exists():
        _fail(f"Settings module not found: {CONFIG_PATH.relative_to(REPO_ROOT)}")
        return set()
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'alias="(STRIPE_[A-Z0-9_]+)"', config_text))


print(f"[billing_contract_check] Importing {BILLING_MODULE} …")
try:
    billing_mod = importlib.import_module(BILLING_MODULE)
    _ok(f"{BILLING_MODULE} imported successfully")
except Exception as exc:
    _fail(f"Cannot import {BILLING_MODULE}: {exc}")
    billing_mod = None

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
                _fail(f"{BILLING_CLASS}.{REQUIRED_METHOD} must accept a 'tenant_id' parameter; found: {params}")
            else:
                _ok(f"{BILLING_CLASS}.{REQUIRED_METHOD}(tenant_id=…) signature is correct")

required_manifest_keys = _stripe_env_aliases()
if not required_manifest_keys:
    _fail("No Stripe env aliases found in backend/app/config.py")

print(f"[billing_contract_check] Checking {K8S_MANIFEST.relative_to(REPO_ROOT)} …")
if not K8S_MANIFEST.exists():
    _fail(f"K8s manifest not found: {K8S_MANIFEST}")
else:
    manifest_text = K8S_MANIFEST.read_text(encoding="utf-8")
    for key in sorted(required_manifest_keys):
        if key not in manifest_text:
            _fail(f"Stripe env alias '{key}' is missing from {K8S_MANIFEST.relative_to(REPO_ROOT)}")
        else:
            _ok(f"K8s manifest contains {key}")

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

print()
if _errors:
    print(f"[billing_contract_check] FAILED — {len(_errors)} error(s) detected.", file=sys.stderr)
    sys.exit(1)

print("[billing_contract_check] All checks passed.")
