#!/usr/bin/env python3
"""Semantic migration probes for GTM seed lifecycle and temporary RLS residue."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine, text

CAPABILITY_NAME = "gtm_outbound_email"
ADAPTER_NAME = "gtm_outbound_email_adapter"
VERSION = "1.0.0"

CAPABILITY_POLICY = "seed_global_gtm_capabilities_policy"
ADAPTER_POLICY = "seed_global_gtm_capability_adapters_policy"


def _load_database_url() -> str:
    url = os.environ.get("AJENDA_DATABASE_URL")
    if not url:
        raise RuntimeError("AJENDA_DATABASE_URL is required for migration semantic probes")
    return url


def _read_seed_rows(connection) -> tuple[dict | None, dict | None]:
    capability = (
        connection.execute(
            text(
                """
            SELECT id, evidence_expectations
            FROM capabilities
            WHERE tenant_id IS NULL
              AND name = :name
              AND version = :version
            """
            ),
            {"name": CAPABILITY_NAME, "version": VERSION},
        )
        .mappings()
        .first()
    )

    adapter = (
        connection.execute(
            text(
                """
            SELECT capability_id, evidence_expectations
            FROM capability_adapters
            WHERE tenant_id IS NULL
              AND name = :name
              AND version = :version
            """
            ),
            {"name": ADAPTER_NAME, "version": VERSION},
        )
        .mappings()
        .first()
    )
    return capability, adapter


def _policy_exists(connection, policy_name: str, table_name: str) -> bool:
    result = connection.execute(
        text(
            """
            SELECT 1
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = :table_name
              AND policyname = :policy_name
            """
        ),
        {"policy_name": policy_name, "table_name": table_name},
    ).first()
    return result is not None


def _ensure_list_of_strings(value: object, *, field_name: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AssertionError(f"{field_name} must be a JSON array")
    if not all(isinstance(item, str) for item in value):
        raise AssertionError(f"{field_name} entries must all be strings")


def _probe_post_upgrade(connection) -> None:
    capability, adapter = _read_seed_rows(connection)
    if capability is None:
        raise AssertionError("missing seeded global capability row after upgrade")
    if adapter is None:
        raise AssertionError("missing seeded global adapter row after upgrade")

    capability_events = capability["evidence_expectations"]
    adapter_events = adapter["evidence_expectations"]

    _ensure_list_of_strings(capability_events, field_name="capabilities.evidence_expectations")
    _ensure_list_of_strings(adapter_events, field_name="capability_adapters.evidence_expectations")

    if capability_events != ["approval_decision", "send_outcome"]:
        raise AssertionError("unexpected capability evidence expectations payload")
    if adapter_events != ["approval_decision", "delivery_outcome"]:
        raise AssertionError("unexpected adapter evidence expectations payload")

    if adapter["capability_id"] != capability["id"]:
        raise AssertionError("seeded adapter does not reference seeded capability")

    if _policy_exists(connection, CAPABILITY_POLICY, "capabilities"):
        raise AssertionError("temporary capability seed policy should be dropped after upgrade")
    if _policy_exists(connection, ADAPTER_POLICY, "capability_adapters"):
        raise AssertionError("temporary adapter seed policy should be dropped after upgrade")


def _probe_post_downgrade(connection) -> None:
    capability, adapter = _read_seed_rows(connection)
    if capability is not None:
        raise AssertionError("seeded global capability row still present after downgrade")
    if adapter is not None:
        raise AssertionError("seeded global adapter row still present after downgrade")

    if _policy_exists(connection, CAPABILITY_POLICY, "capabilities"):
        raise AssertionError("temporary capability seed policy should be dropped after downgrade")
    if _policy_exists(connection, ADAPTER_POLICY, "capability_adapters"):
        raise AssertionError("temporary adapter seed policy should be dropped after downgrade")


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic migration checks for GTM seed lifecycle")
    parser.add_argument("--stage", choices=("post-upgrade", "post-downgrade"), required=True)
    args = parser.parse_args()

    engine = create_engine(_load_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if args.stage == "post-upgrade":
                _probe_post_upgrade(connection)
            else:
                _probe_post_downgrade(connection)
    finally:
        engine.dispose()

    print(f"PASS: migration semantic probe succeeded for {args.stage}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
