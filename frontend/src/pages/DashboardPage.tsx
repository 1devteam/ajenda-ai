import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listMissions, listProviderCredentials, listReviewQueue } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import StatCard from "../components/ui/StatCard";
import MissionFlow from "../components/ui/MissionFlow";
import MissionCard from "../components/ui/MissionCard";
import LoadingState from "../components/ui/LoadingState";
import { useWorkspaceSummary } from "../hooks/useWorkspaceSummary";
import { readWizardCompletedAt } from "../utils/standaloneWizard";
import type { MissionListItem } from "../types";

function usagePercent(current: number, limit: number): number | null {
  if (limit < 0 || limit === 0) {
    return null;
  }
  return Math.round((current / limit) * 100);
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { me, plan, usage, error, loading } = useWorkspaceSummary(session);
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [connectedTools, setConnectedTools] = useState<string[]>([]);
  const [dataLoading, setDataLoading] = useState(true);

  const wizardDone = session ? readWizardCompletedAt(session.tenantId) !== null : false;
  const emailVerified =
    me?.membership?.status === "active" || me?.tenant.status === "active" || session?.authMode === "oidc";

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    async function load() {
      if (!session) {
        return;
      }
      setDataLoading(true);
      try {
        const [missionResponse, reviewResponse, credentialResponse] = await Promise.all([
          listMissions(session, { limit: 50 }),
          listReviewQueue(session, { status: "pending", limit: 50 }),
          listProviderCredentials(session),
        ]);
        if (!cancelled) {
          setMissions(missionResponse.missions);
          setPendingApprovals(reviewResponse.total);
          setConnectedTools(
            credentialResponse.credentials
              .filter((item) => item.enabled && !item.revoked)
              .map((item) => item.credential_id),
          );
        }
      } finally {
        if (!cancelled) {
          setDataLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [session?.tenantId, session?.apiKey, session?.accessToken]);

  const flowSteps = useMemo(() => {
    const planned = missions.filter((m) => m.status === "planned").length;
    const running = missions.filter((m) => m.status === "running").length;
    const completed = missions.filter((m) => m.status === "completed").length;
    const other = missions.length - planned - running - completed;
    return [
      { id: "goal", label: "Goal defined", count: planned + other },
      { id: "planning", label: "Planning complete", count: planned },
      { id: "queued", label: "Queued work", count: running },
      { id: "executing", label: "Executing", count: running },
      { id: "evidence", label: "Verifying evidence", count: pendingApprovals },
      { id: "completed", label: "Completed results", count: completed },
    ];
  }, [missions, pendingApprovals]);

  const activeMissions = missions.filter((m) => m.status === "running" || m.status === "planned").length;
  const completedToday = missions.filter((m) => {
    if (m.status !== "completed") {
      return false;
    }
    const updated = new Date(m.updated_at);
    const now = new Date();
    return updated.toDateString() === now.toDateString();
  }).length;
  const successRate =
    missions.length === 0
      ? "—"
      : `${Math.round((missions.filter((m) => m.status === "completed").length / missions.length) * 100)}%`;

  const recentResults = missions.slice(0, 5);

  return (
    <main>
      <PageHeader
        eyebrow="Command center"
        title={me?.tenant.name ? `Welcome back, ${me.tenant.name}` : "Your command center"}
        lead="Ajenda breaks goals into governed steps, executes work through your connections, and returns evidence you can trust."
        actions={
          <button type="button" className="primary-button" onClick={() => navigate("/missions")}>
            Launch mission
          </button>
        }
      />

      {!emailVerified ? (
        <section className="notice-banner">
          <strong>Finish onboarding</strong>
          <Link className="primary-link" to="/verify-email">
            Verify your email
          </Link>
        </section>
      ) : null}

      {usage && usagePercent(usage.usage.api_calls_count ?? 0, usage.limits.api_calls_per_month ?? -1) !== null
        ? (() => {
            const pct = usagePercent(usage.usage.api_calls_count ?? 0, usage.limits.api_calls_per_month ?? -1)!;
            if (pct < 80) {
              return null;
            }
            return (
              <section className="notice-banner quota-warning">
                <strong>API usage at {pct}%</strong>
                <button type="button" className="ghost-button" onClick={() => navigate("/billing")}>
                  Open billing
                </button>
              </section>
            );
          })()
        : null}

      {loading || dataLoading ? <LoadingState label="Loading command center..." /> : null}

      <section className="cc-stat-grid">
        <StatCard label="Active missions" value={activeMissions} hint="Planned or in progress" />
        <StatCard label="Waiting for approval" value={pendingApprovals} hint="Review before send" />
        <StatCard label="Completed today" value={completedToday} hint="Finished outcomes" />
        <StatCard label="Success rate" value={successRate} hint={`${missions.length} total missions`} />
      </section>

      <section className="panel" style={{ marginBottom: "1rem" }}>
        <h2>Mission flow</h2>
        <p className="muted">Where work sits across your governed pipeline.</p>
        <MissionFlow steps={flowSteps} activeStepId={activeFlowStep(flowSteps)} />
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-heading-row">
            <h2>Recent results</h2>
            <Link className="ghost-link" to="/results">
              View all
            </Link>
          </div>
          {recentResults.length === 0 ? (
            <p className="muted">No missions yet. Launch your first mission to see outcomes here.</p>
          ) : (
            <div className="action-list">
              {recentResults.map((mission) => (
                <MissionCard
                  key={mission.mission_id}
                  missionId={mission.mission_id}
                  title={mission.objective}
                  status={mission.status}
                  meta={new Date(mission.updated_at).toLocaleString()}
                />
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <h2>Connected tools</h2>
          <p className="muted">Plugins and credentials available to this workspace.</p>
          <div className="cc-connected-tools">
            {connectedTools.length === 0 ? (
              <span className="cc-tool-chip">Ajenda brain (standalone)</span>
            ) : (
              connectedTools.map((tool) => (
                <span key={tool} className="cc-tool-chip connected">
                  {tool}
                </span>
              ))
            )}
          </div>
          <div className="action-list" style={{ marginTop: "1rem" }}>
            <Link className="action-link" to="/connections">
              Manage connections
            </Link>
            <Link className="action-link" to="/approvals">
              Open approvals ({pendingApprovals})
            </Link>
          </div>
        </div>
      </section>

      {!wizardDone ? (
        <section className="notice-banner">
          <strong>Complete business memory setup</strong>
          <Link className="primary-link" to="/setup">
            Open setup wizard
          </Link>
        </section>
      ) : null}

      <section className="grid two">
        <div className="panel">
          <h2>Plan</h2>
          <p>
            <strong>{plan?.display_name ?? me?.tenant.plan ?? "..."}</strong>
          </p>
          <p className="muted">{plan?.features_enabled.length ?? 0} capabilities enabled</p>
        </div>
        <div className="panel">
          <h2>Usage this month</h2>
          <p>
            API calls:{" "}
            <strong>
              {usage
                ? `${usage.usage.api_calls_count ?? 0} / ${usage.limits.api_calls_per_month ?? "∞"}`
                : "..."}
            </strong>
          </p>
        </div>
      </section>

      <PageErrorAlert error={error} />
    </main>
  );
}

function activeFlowStep(steps: { id: string; count: number }[]): string | undefined {
  const executing = steps.find((s) => s.id === "executing");
  if (executing && executing.count > 0) {
    return "executing";
  }
  const evidence = steps.find((s) => s.id === "evidence");
  if (evidence && evidence.count > 0) {
    return "evidence";
  }
  return undefined;
}