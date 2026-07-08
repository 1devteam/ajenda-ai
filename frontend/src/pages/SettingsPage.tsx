import { Link } from "react-router-dom";
import { useWorkspaceSummary } from "../hooks/useWorkspaceSummary";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import LoadingState from "../components/ui/LoadingState";
import StatusBadge from "../components/ui/StatusBadge";

export default function SettingsPage() {
  const { session } = useAuth();
  const { me, plan, usage, error, loading } = useWorkspaceSummary(session);

  if (loading && !me) {
    return <LoadingState label="Loading account settings..." />;
  }

  return (
    <main>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        lead="Account, team context, and workspace preferences."
      />

      <section className="grid two">
        <article className="panel">
          <h2>Account</h2>
          <p>
            <strong>{me?.tenant.name ?? "Workspace"}</strong>
          </p>
          <p className="muted">{me?.membership?.email ?? me?.principal.email ?? "—"}</p>
          <p>
            Plan: <strong>{plan?.display_name ?? me?.tenant.plan ?? "—"}</strong>
          </p>
          <StatusBadge status={me?.tenant.status ?? "unknown"} />
        </article>

        <article className="panel">
          <h2>Usage this month</h2>
          {usage ? (
            <ul className="action-list">
              <li className="action-row">
                <span>API calls</span>
                <strong>{usage.usage.api_calls_count ?? 0}</strong>
              </li>
              <li className="action-row">
                <span>Missions created</span>
                <strong>{usage.usage.missions_created ?? 0}</strong>
              </li>
              <li className="action-row">
                <span>Work items</span>
                <strong>{usage.usage.tasks_created ?? 0}</strong>
              </li>
            </ul>
          ) : (
            <p className="muted">Usage unavailable.</p>
          )}
        </article>
      </section>

      <section className="panel">
        <h2>Preferences & security</h2>
        <div className="action-list">
          <Link className="action-link" to="/connections">
            Manage connections and API credentials
          </Link>
          <Link className="action-link" to="/billing">
            Billing and plan management
          </Link>
          <Link className="action-link" to="/business">
            Business memory and profile facts
          </Link>
          <Link className="action-link" to="/setup">
            Standalone setup wizard
          </Link>
        </div>
        <p className="muted">
          API keys are issued during onboarding. Contact your workspace owner to rotate operational keys.
        </p>
      </section>

      <PageErrorAlert error={error} />
    </main>
  );
}