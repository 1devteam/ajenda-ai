import { useEffect, useState } from "react";
import { getAccountMe, getAccountPlan, getAccountUsage } from "../api/client";
import type { CustomerSession } from "../types";
import { saveSession } from "../auth/session";
import type { AccountMeResponse, AccountPlanResponse, AccountUsageResponse } from "../types";

export function useWorkspaceSummary(session: CustomerSession | null) {
  const [me, setMe] = useState<AccountMeResponse | null>(null);
  const [plan, setPlan] = useState<AccountPlanResponse | null>(null);
  const [usage, setUsage] = useState<AccountUsageResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) {
      setMe(null);
      setPlan(null);
      setUsage(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    async function load() {
      try {
        const [meResponse, planResponse, usageResponse] = await Promise.all([
          getAccountMe(session!),
          getAccountPlan(session!),
          getAccountUsage(session!),
        ]);
        if (cancelled) {
          return;
        }
        setMe(meResponse);
        setPlan(planResponse);
        setUsage(usageResponse);
        setError(null);
        if (
          session!.plan !== meResponse.tenant.plan ||
          session!.slug !== meResponse.tenant.slug
        ) {
          saveSession({
            ...session!,
            plan: meResponse.tenant.plan,
            slug: meResponse.tenant.slug,
            orgName: meResponse.tenant.name,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [session?.tenantId, session?.apiKey, session?.accessToken]);

  return { me, plan, usage, error, loading };
}