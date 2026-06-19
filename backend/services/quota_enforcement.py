"""QuotaEnforcementService — SaaS plan limit and feature gate enforcement.

This service is the single enforcement point for all subscription-tier limits.
It is called by mutation routes before any work is accepted into the system.

Enforcement contract:
  - check_and_record_mission_creation: raises QuotaExceededError if the tenant
    has reached their monthly mission limit, otherwise increments the counter.
  - check_and_record_task_creation: raises QuotaExceededError if the tenant
    has reached their monthly task limit, otherwise increments the counter.
  - check_and_record_agent_provisioning: raises QuotaExceededError if the
    fleet would exceed the per-fleet agent limit.
  - require_feature: raises FeatureNotAvailableError if the tenant's plan
    does not include the requested feature.
  - check_tenant_active: raises the appropriate error if the tenant is
    suspended or deleted (defense-in-depth; middleware checks first).

All methods are synchronous and designed to be called inside a DB transaction.
The caller is responsible for committing after the business operation succeeds.

Design decisions:
  - Quota checks and counter increments are done in the same transaction as
    the business operation. If the business operation rolls back, the counter
    is also rolled back — no phantom increments.
  - The TenantPlan.UNLIMITED sentinel (-1) bypasses all limit checks so that
    enterprise plans never hit artificial ceilings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.repositories.tenant_repository import (
    TenantRepository,
)


class QuotaExceededError(ValueError):
    """Raised when a tenant has exceeded a plan limit.

    HTTP layer should map this to 402 Payment Required.
    """

    def __init__(self, field: str, limit: int, current: int, plan: str) -> None:
        self.field = field
        self.limit = limit
        self.current = current
        self.plan = plan
        super().__init__(
            f"Quota exceeded for {field!r}: current={current}, limit={limit} "
            f"(plan={plan!r}). Upgrade your plan to continue."
        )


class FeatureNotAvailableError(ValueError):
    """Raised when a tenant's plan does not include a required feature.

    HTTP layer should map this to 402 Payment Required.
    """

    def __init__(self, feature: str, plan: str) -> None:
        self.feature = feature
        self.plan = plan
        super().__init__(
            f"Feature {feature!r} is not available on plan {plan!r}. Upgrade your plan to access this feature."
        )


class BudgetGateDeniedError(ValueError):
    """Raised when an opt-in budget gate denies mission intake limits."""

    def __init__(self, *, field: str, limit: int, proposed: int, plan: str) -> None:
        self.field = field
        self.limit = limit
        self.proposed = proposed
        self.plan = plan
        super().__init__(f"Budget gate denied for {field!r}: proposed={proposed}, limit={limit} (plan={plan!r}).")


@dataclass(frozen=True)
class QuotaStatus:
    """Summary of a tenant's current quota consumption."""

    tenant_id: str
    plan: str
    billing_period: str
    missions_created: int
    missions_limit: int
    tasks_created: int
    tasks_limit: int
    agents_provisioned: int
    api_calls_count: int
    api_calls_limit: int


class QuotaEnforcementService:
    """Central enforcement point for SaaS subscription limits and feature gates.

    Inject this service into any route or service that creates resources or
    accesses gated features.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)

    # ------------------------------------------------------------------
    # Tenant lifecycle gate (defense-in-depth)
    # ------------------------------------------------------------------

    def check_tenant_active(self, tenant_id: uuid.UUID) -> None:
        """Raise if the tenant is not active.

        This is a defense-in-depth check. TenantContextMiddleware performs
        the primary check at the HTTP layer. This check catches cases where
        the tenant is suspended between the middleware check and the service
        call (e.g., in a long-running transaction).
        """
        self._tenants.get_active(tenant_id)  # raises TenantSuspendedError / TenantDeletedError

    # ------------------------------------------------------------------
    # Resource quota checks + counter increments
    # ------------------------------------------------------------------

    def check_and_record_mission_creation(self, tenant_id: uuid.UUID) -> None:
        """Check mission quota and increment counter atomically.

        Must be called inside the same transaction as the Mission.create().
        Raises QuotaExceededError if the limit is reached.
        """
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            # Unknown plan — fail open with a warning (don't block the user)
            return

        usage = self._tenants.get_or_create_usage(tenant_id)
        limit = plan.max_missions_per_month

        if limit != -1 and usage.missions_created >= limit:
            raise QuotaExceededError(
                field="missions_per_month",
                limit=limit,
                current=usage.missions_created,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(tenant_id, field="missions_created")
        self._report_metered_if_possible(tenant_id, 1, "missions")

    def check_and_record_task_creation(
        self,
        tenant_id: uuid.UUID,
        *,
        count: int = 1,
    ) -> None:
        """Check task quota and increment counter atomically.

        Must be called inside the same transaction as the ExecutionTask.create().
        Raises QuotaExceededError if the limit is reached.

        Args:
            tenant_id: The tenant to check quota for.
            count: Number of tasks being created in this call. Defaults to 1.
                   Use count=N when a single route call enqueues multiple tasks
                   (e.g., POST /missions/{id}/queue with N planned tasks) to
                   prevent tenants from bypassing max_tasks_per_month by
                   batching large missions.

        Raises:
            ValueError: If count < 1.
            QuotaExceededError: If the current usage + count would exceed the limit.
        """
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count}")

        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        usage = self._tenants.get_or_create_usage(tenant_id)
        limit = plan.max_tasks_per_month

        if limit != -1 and usage.tasks_created + count > limit:
            raise QuotaExceededError(
                field="tasks_per_month",
                limit=limit,
                current=usage.tasks_created,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(tenant_id, field="tasks_created", amount=count)
        self._report_metered_if_possible(tenant_id, count, "tasks")

    def check_and_record_agent_provisioning(
        self,
        tenant_id: uuid.UUID,
        *,
        agents_requested: int,
    ) -> None:
        """Check per-fleet agent limit and increment counter atomically.

        Raises QuotaExceededError if provisioning agents_requested agents
        would exceed the plan's max_agents_per_fleet limit.
        """
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        limit = plan.max_agents_per_fleet
        if limit != -1 and agents_requested > limit:
            raise QuotaExceededError(
                field="agents_per_fleet",
                limit=limit,
                current=agents_requested,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(
            tenant_id,
            field="agents_provisioned",
            amount=agents_requested,
        )
        self._report_metered_if_possible(tenant_id, agents_requested, "agents")

    def check_api_key_limit(self, tenant_id: uuid.UUID, *, current_key_count: int) -> None:
        """Check that the tenant has not exceeded their API key limit.

        Does not increment any counter (API keys are a gauge, not a rate).
        Raises QuotaExceededError if the limit is reached.
        """
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        limit = plan.max_api_keys
        if limit != -1 and current_key_count >= limit:
            raise QuotaExceededError(
                field="api_keys",
                limit=limit,
                current=current_key_count,
                plan=tenant.plan,
            )

    def check_and_record_api_call(self, tenant_id: uuid.UUID) -> None:
        """Check monthly API call quota and increment counter atomically.

        Intended to be called for authenticated API requests (e.g. from rate
        limit middleware after allowing the request). Raises QuotaExceededError
        if the tenant has reached max_monthly_api_calls for the plan.
        """
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        usage = self._tenants.get_or_create_usage(tenant_id)
        limit = plan.max_monthly_api_calls

        if limit != -1 and usage.api_calls_count >= limit:
            raise QuotaExceededError(
                field="api_calls_per_month",
                limit=limit,
                current=usage.api_calls_count,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(tenant_id, field="api_calls_count")
        self._report_metered_if_possible(tenant_id, 1, "api_calls")

    # ------------------------------------------------------------------
    # Feature gate
    # ------------------------------------------------------------------

    def require_feature(self, tenant_id: uuid.UUID, feature: str) -> None:
        """Raise FeatureNotAvailableError if the tenant's plan lacks the feature.

        Use this to gate premium features (e.g., compliance layer, webhooks,
        custom OIDC providers) behind plan tiers.
        """
        from backend.services.feature_flag_service import FeatureFlagService

        tenant = self._tenants.get_active(tenant_id)
        if not FeatureFlagService(self._session, tenants=self._tenants).is_enabled(tenant_id, feature):
            raise FeatureNotAvailableError(feature=feature, plan=tenant.plan)

    # ------------------------------------------------------------------
    # Quota status (read-only)
    # ------------------------------------------------------------------

    def get_quota_status(self, tenant_id: uuid.UUID) -> QuotaStatus:
        """Return a read-only summary of the tenant's current quota consumption."""
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        usage = self._tenants.get_or_create_usage(tenant_id)

        from datetime import date

        period = date.today().replace(day=1)

        return QuotaStatus(
            tenant_id=str(tenant_id),
            plan=tenant.plan,
            billing_period=str(period),
            missions_created=usage.missions_created,
            missions_limit=plan.max_missions_per_month if plan else -1,
            tasks_created=usage.tasks_created,
            tasks_limit=plan.max_tasks_per_month if plan else -1,
            agents_provisioned=usage.agents_provisioned,
            api_calls_count=usage.api_calls_count,
            api_calls_limit=plan.max_monthly_api_calls if plan else -1,
        )

    def enforce_mission_budget_gate(self, tenant_id: uuid.UUID, budget_limits: dict[str, object] | None) -> None:
        """Optionally enforce budget policy gates for selected tenants/plans."""
        if not budget_limits:
            return
        settings = get_settings()
        if (
            not settings.budget_policy_enabled
            or settings.budget_policy_observe_only
            or not settings.budget_policy_enforce
        ):
            return

        tenant = self._tenants.get_active(tenant_id)
        tenant_id_norm = str(tenant_id).strip().lower()
        plan_norm = str(tenant.plan).strip().lower()
        tenant_opt_in = tenant_id_norm in settings.budget_policy_enforce_tenant_id_set
        plan_opt_in = plan_norm in settings.budget_policy_enforce_plan_set
        if not tenant_opt_in and not plan_opt_in:
            return

        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        max_tasks = budget_limits.get("max_tasks")
        if isinstance(max_tasks, int):
            limit = plan.max_tasks_per_month
            if limit != -1 and max_tasks > limit:
                raise BudgetGateDeniedError(
                    field="max_tasks",
                    limit=limit,
                    proposed=max_tasks,
                    plan=tenant.plan,
                )

    # ------------------------------------------------------------------
    # Metering bridge to Stripe (PR3) — best effort, never blocks
    # ------------------------------------------------------------------

    def _report_metered_if_possible(self, tenant_id: uuid.UUID, amount: int, metric: str) -> None:
        try:
            from backend.services.billing_stripe_integration import StripeBillingService

            billing = StripeBillingService(self._session)
            billing.report_metered_usage(tenant_id, amount, metric=metric)
        except Exception:
            # Metering is best-effort; log would be noisy in unit tests.
            pass
