"""Real-Postgres proof for the standard SaaS pricing-tier capacity contract."""

from __future__ import annotations

from sqlalchemy import text


def test_standard_pricing_tier_capacity_contract(pg_session) -> None:  # type: ignore[no-untyped-def]
    rows = pg_session.execute(
        text(
            """
            SELECT
                slug,
                max_missions_per_month,
                max_tasks_per_month,
                max_agents_per_fleet,
                max_concurrent_workers,
                max_api_keys,
                max_monthly_api_calls,
                features_enabled
            FROM tenant_plans
            WHERE slug IN ('free', 'starter', 'pro', 'enterprise')
            ORDER BY slug
            """
        )
    ).mappings()

    plans = {row["slug"]: row for row in rows}

    assert set(plans) == {"free", "starter", "pro", "enterprise"}

    assert _limits(plans["free"]) == (25, 500, 2, 1, 2, 5_000)
    assert _limits(plans["starter"]) == (100, 5_000, 5, 3, 5, 50_000)
    assert _limits(plans["pro"]) == (500, 50_000, 25, 10, 20, 500_000)
    assert _limits(plans["enterprise"]) == (-1, -1, -1, -1, -1, -1)

    # This PR changes capacity only. Preserve the existing capability ladder.
    assert plans["free"]["features_enabled"] == []
    assert plans["starter"]["features_enabled"] == ["webhooks"]
    assert set(plans["pro"]["features_enabled"]) == {
        "webhooks",
        "compliance_layer",
        "custom_oidc",
        "audit_export",
        "ability_runtime",
        "gtm",
    }
    assert set(plans["enterprise"]["features_enabled"]) == {
        "webhooks",
        "compliance_layer",
        "custom_oidc",
        "audit_export",
        "ability_runtime",
        "sso",
        "custom_retention",
        "dedicated_workers",
        "sla_support",
        "gtm",
    }


def _limits(row) -> tuple[int, int, int, int, int, int]:  # type: ignore[no-untyped-def]
    return (
        row["max_missions_per_month"],
        row["max_tasks_per_month"],
        row["max_agents_per_fleet"],
        row["max_concurrent_workers"],
        row["max_api_keys"],
        row["max_monthly_api_calls"],
    )
