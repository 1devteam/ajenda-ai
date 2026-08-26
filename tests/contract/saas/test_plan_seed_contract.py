from __future__ import annotations

from sqlalchemy import select

from backend.domain.tenant_plan import TenantPlan


def test_free_plan_seed_contract(pg_session) -> None:
    free_plan = pg_session.execute(select(TenantPlan).where(TenantPlan.slug == "free")).scalar_one()

    assert free_plan.max_missions_per_month == 25
    assert free_plan.max_tasks_per_month == 500
    assert free_plan.max_agents_per_fleet == 2
    assert free_plan.max_concurrent_workers == 1
    assert free_plan.max_api_keys == 2
    # API-call capacity now refers only to billable external API-key traffic.
    assert free_plan.max_monthly_api_calls == 5_000
    assert free_plan.features_enabled == []
