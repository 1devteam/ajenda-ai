import { useMemo } from "react";
import { useNavigate } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import Button from "../components/primitives/Button";
import Card from "../components/primitives/Card";
import MetricsRow, { type MetricItem } from "../components/dashboard/MetricsRow";
import ActiveWorkPanel from "../components/dashboard/ActiveWorkPanel";
import AttentionBanner from "../components/dashboard/AttentionBanner";
import OnboardingChecklist from "../components/dashboard/OnboardingChecklist";
import LiveRegion from "../components/states/LiveRegion";
import { useWorkspaceSummary } from "../hooks/useWorkspaceSummary";
import { useDashboardData } from "../hooks/useDashboardData";
import {
  buildOnboardingChecklist,
  checklistIncomplete,
  countCompletedToday,
  isActiveMission,
  resolveAttentionBanner,
  resolvePrimaryAction,
  successRateLabelFromCounts,
  usagePercent,
} from "../dashboard/dashboardModel";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { me, plan, usage, error, loading: summaryLoading } = useWorkspaceSummary(session);
  const {
    missions,
    pendingApprovals,
    hasConnections,
    onboarding,
    missionTotalCount,
    missionCompletedCount,
    loading: dataLoading,
    error: dataError,
    liveMessage,
    reload,
  } = useDashboardData(session);

  const wizardDone = onboarding?.completed ?? false;
  const emailVerified =
    me?.membership?.status === "active" ||
    me?.tenant.status === "active" ||
    session?.authMode === "oidc";

  const activeMissions = useMemo(() => missions.filter(isActiveMission).length, [missions]);
  const completedToday = useMemo(() => countCompletedToday(missions), [missions]);
  const successRate = useMemo(
    () => successRateLabelFromCounts(missionCompletedCount, missionTotalCount),
    [missionCompletedCount, missionTotalCount],
  );

  const quotaPct = useMemo(() => {
    if (!usage) {
      return null;
    }
    return usagePercent(usage.usage.api_calls_count ?? 0, usage.limits.api_calls_per_month ?? -1);
  }, [usage]);

  const primaryAction = useMemo(
    () =>
      resolvePrimaryAction({
        pendingApprovals,
        wizardDone,
        emailVerified: Boolean(emailVerified),
      }),
    [pendingApprovals, wizardDone, emailVerified],
  );

  const banner = useMemo(
    () =>
      resolveAttentionBanner({
        quotaPct,
        wizardDone,
        emailVerified: Boolean(emailVerified),
      }),
    [quotaPct, wizardDone, emailVerified],
  );

  const checklist = useMemo(
    () =>
      buildOnboardingChecklist({
        wizardDone,
        hasConnections,
        hasLaunchedMission: missions.length > 0,
      }),
    [wizardDone, hasConnections, missions.length],
  );

  const showChecklist = checklistIncomplete(checklist);

  const metrics: MetricItem[] = [
    {
      id: "active",
      label: "Active missions",
      value: activeMissions,
      hint: "Planned or running",
      to: "/active-work",
    },
    {
      id: "approvals",
      label: "Approvals waiting",
      value: pendingApprovals,
      hint: pendingApprovals > 0 ? "Needs your review" : "Queue clear",
      to: "/approvals",
    },
    {
      id: "outcomes",
      label: "Completed today",
      value: completedToday,
      hint: "Recent outcomes",
      to: "/results",
    },
    {
      id: "success",
      label: "Success rate",
      value: successRate,
      hint: `${missionTotalCount} total missions`,
      to: "/results",
    },
  ];

  const loading = summaryLoading || dataLoading;

  return (
    <div className="@container mx-auto max-w-7xl">
      <LiveRegion message={liveMessage} />

      <PageHeader
        eyebrow="Command center"
        title={me?.tenant.name ? `Welcome back, ${me.tenant.name}` : "Welcome back to ajenda-ai"}
        lead="A clear view of work in motion, decisions waiting, and outcomes delivered."
      />

      <section className="cc-next-action" aria-label="Next best action">
        <div>
          <p>Next best action</p>
          <strong>{primaryAction.label}</strong>
        </div>
        <Button variant="primary" onClick={() => navigate(primaryAction.to)}>
          Open
        </Button>
      </section>

      {banner ? <AttentionBanner banner={banner} /> : null}

      {showChecklist ? <OnboardingChecklist steps={checklist} /> : null}

      <section className="mb-6 space-y-6 @lg:mb-8">
        <MetricsRow
          metrics={metrics}
          loading={loading}
          error={dataError}
          onRetry={reload}
        />

        <div className="grid grid-cols-1 gap-4 @lg:grid-cols-2 @lg:gap-6">
          <ActiveWorkPanel
            missions={missions}
            loading={dataLoading}
            error={dataError}
            onRetry={reload}
            onLaunch={() => navigate("/missions")}
          />
          <Card elevated className="cc-tips-panel">
            <p className="cc-section-kicker">Ajenda tips</p>
            <h2 className="font-display text-lg font-semibold text-zinc-100">Keep missions outcome-first</h2>
            <p>Include the market, the result you want, and anything Ajenda must not do.</p>
            <ul>
              <li>Say “draft” when you want review before sending.</li>
              <li>Use Connections only to link business accounts.</li>
              <li>Completed work and evidence live together in Results.</li>
            </ul>
            <Button variant="ghost" onClick={() => navigate("/missions")}>Plan a mission</Button>
          </Card>
        </div>

        <div className="grid grid-cols-1 gap-4 @md:grid-cols-2 @md:gap-6">
          <Card elevated>
            <h2 className="font-display text-base font-semibold text-zinc-100">Plan</h2>
            <p className="mt-2 text-lg font-medium text-zinc-50">
              {plan?.display_name ?? me?.tenant.plan ?? "…"}
            </p>
            <p className="mt-1 text-sm text-zinc-500">
              {plan?.features_enabled.length ?? 0} capabilities enabled
            </p>
          </Card>
          <Card elevated>
            <h2 className="font-display text-base font-semibold text-zinc-100">Usage this month</h2>
            <p className="mt-2 text-lg font-medium text-zinc-50">
              {usage
                ? `${usage.usage.api_calls_count ?? 0} / ${usage.limits.api_calls_per_month ?? "∞"} API calls`
                : "…"}
            </p>
          </Card>
        </div>
      </section>

      <PageErrorAlert error={error} />
    </div>
  );
}
