import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAccountMe, getAccountPlan, getAccountUsage, listProviderCredentials } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { saveSession } from "../auth/session";
import type { AccountMeResponse, AccountPlanResponse, AccountUsageResponse } from "../types";
import { failureText } from "../utils/errors";
import { readWizardCompletedAt } from "../utils/standaloneWizard";

function formatLimit(current: number, limit: number): string {
  if (limit < 0) {
    return `${current} / unlimited`;
  }
  return `${current} / ${limit}`;
}

function usagePercent(current: number, limit: number): number | null {
  if (limit < 0 || limit === 0) {
    return null;
  }
  return Math.round((current / limit) * 100);
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const [me, setMe] = useState<AccountMeResponse | null>(null);
  const [plan, setPlan] = useState<AccountPlanResponse | null>(null);
  const [usage, setUsage] = useState<AccountUsageResponse | null>(null);
  const [credentialCount, setCredentialCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const wizardDone = session ? readWizardCompletedAt(session.tenantId) !== null : false;

  const emailVerified =
    me?.membership?.status === "active" || me?.tenant.status === "active" || session?.authMode === "oidc";
  const signedIn = session !== null;
  const credentialsConnected = credentialCount !== null && credentialCount > 0;
  const showOnboardingChecklist = signedIn && (!emailVerified || !credentialsConnected);

  useEffect(() => {
    if (!session) {
      return;
    }

    let cancelled = false;

    async function load() {
      if (!session) {
        return;
      }
      try {
        const [meResponse, planResponse, usageResponse, credentialsResponse] = await Promise.all([
          getAccountMe(session),
          getAccountPlan(session),
          getAccountUsage(session),
          listProviderCredentials(session),
        ]);
        if (!cancelled) {
          setMe(meResponse);
          setPlan(planResponse);
          setUsage(usageResponse);
          setCredentialCount(credentialsResponse.credentials.length);
          if (session.plan !== meResponse.tenant.plan || session.slug !== meResponse.tenant.slug) {
            saveSession({
              ...session,
              plan: meResponse.tenant.plan,
              slug: meResponse.tenant.slug,
              orgName: meResponse.tenant.name,
            });
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [session?.tenantId, session?.apiKey, session?.accessToken]);

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>{me?.tenant.name ?? "Your workspace"}</h1>
          <p>
            Plan <strong>{me?.tenant.plan ?? "..."}</strong> · slug{" "}
            <strong>{me?.tenant.slug ?? "..."}</strong>
          </p>
        </div>
        <div className="status-card">
          <span className={`status-dot ${me?.tenant.status === "active" ? "ok" : ""}`} />
          <div>
            <strong>{me?.tenant.status ?? "loading"}</strong>
            <small>{me?.membership?.email ?? me?.principal.email ?? "Tenant owner"}</small>
          </div>
        </div>
      </section>

      {showOnboardingChecklist ? (
        <section className="notice-banner">
          <strong>Finish onboarding</strong>
          <ul className="onboarding-checklist">
            {!emailVerified ? (
              <li>
                <span>Verify your email</span>
                <Link className="primary-link" to="/verify-email">
                  Open verify page
                </Link>
              </li>
            ) : (
              <li className="done">✓ Email verified</li>
            )}
            <li className={signedIn ? "done" : undefined}>
              {signedIn ? "✓ Signed in" : <Link to="/signin">Sign in</Link>}
            </li>
            <li className={credentialsConnected ? "done" : undefined}>
              {credentialsConnected ? (
                "✓ Provider credentials connected"
              ) : (
                <>
                  <span>Connect provider credentials</span>
                  <Link className="primary-link" to="/credentials">
                    Open credentials
                  </Link>
                </>
              )}
            </li>
          </ul>
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
                <span>
                  {pct >= 100
                    ? "You have hit your monthly API call limit. Upgrade or wait for the next billing period."
                    : "You are approaching your monthly API call limit."}
                </span>
                <button type="button" className="ghost-button" onClick={() => navigate("/billing")}>
                  Open billing
                </button>
              </section>
            );
          })()
        : null}

      <section className="stat-grid">
        <article className="stat-card">
          <span className="stat-label">Plan</span>
          <strong>{plan?.display_name ?? me?.tenant.plan ?? "..."}</strong>
          <small>{plan?.features_enabled.length ?? 0} feature flags enabled</small>
        </article>
        <article className="stat-card">
          <span className="stat-label">Missions this month</span>
          <strong>
            {usage
              ? formatLimit(usage.usage.missions_created ?? 0, usage.limits.missions_per_month ?? -1)
              : "..."}
          </strong>
          <small>Billing period {usage?.billing_period ?? "..."}</small>
        </article>
        <article className="stat-card">
          <span className="stat-label">Tasks this month</span>
          <strong>
            {usage
              ? formatLimit(usage.usage.tasks_created ?? 0, usage.limits.tasks_per_month ?? -1)
              : "..."}
          </strong>
          <small>Queue-backed worker execution</small>
        </article>
        <article className="stat-card">
          <span className="stat-label">API calls</span>
          <strong>
            {usage
              ? formatLimit(usage.usage.api_calls_count ?? 0, usage.limits.api_calls_per_month ?? -1)
              : "..."}
          </strong>
          <small>Monthly quota meter</small>
        </article>
      </section>

      {!wizardDone ? (
        <section className="notice-banner">
          <strong>Finish standalone brain setup</strong>
          <span>
            Run the setup wizard to save business profile facts and sync internal records for hybrid
            retrieval.
          </span>
          <Link className="primary-link" to="/setup">
            Open setup wizard
          </Link>
        </section>
      ) : null}

      <section className="grid two">
        <div className="panel">
          <h2>Next steps</h2>
          <div className="action-list">
            <Link className="action-link" to="/setup">
              Standalone setup wizard (profile → records → plugins)
            </Link>
            <Link className="action-link" to="/billing">
              Upgrade plan or open billing portal
            </Link>
            <Link className="action-link" to="/business">
              Edit business info (name, contacts, market)
            </Link>
            <Link className="action-link" to="/missions">
              Create a mission with a clear outcome
            </Link>
            <Link className="action-link" to="/tasks">
              Launch a runtime proof task
            </Link>
          </div>
        </div>

        <div className="panel">
          <h2>Plan limits</h2>
          {plan ? (
            <pre>{JSON.stringify(plan.limits, null, 2)}</pre>
          ) : (
            <p className="muted">Loading plan details...</p>
          )}
        </div>
      </section>

      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}