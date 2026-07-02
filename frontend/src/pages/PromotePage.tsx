import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAccountMe, promoteBootstrapKey } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { beginOidcRedirect } from "../auth/oidc";
import { isOperational, saveSession } from "../auth/session";
import OidcProviderButton from "../components/OidcProviderButton";
import PageErrorAlert from "../components/PageErrorAlert";
import { copyToClipboard } from "../utils/clipboard";

interface ActivatedCredentials {
  tenantId: string;
  apiKey: string;
  orgName?: string;
  slug?: string;
}

export default function PromotePage() {
  const navigate = useNavigate();
  const { session, oidcConfig: config, oidcEnabled, refreshSession } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [activated, setActivated] = useState<ActivatedCredentials | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      navigate("/signin", { replace: true });
      return;
    }

    if (isOperational(session) && !activated) {
      navigate("/dashboard", { replace: true });
    }
  }, [activated, navigate, session]);

  async function handleCopy(field: string, value: string) {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopiedField(field);
      window.setTimeout(() => {
        setCopiedField((current) => (current === field ? null : current));
      }, 2000);
    }
  }

  async function handleGoogleSignIn() {
    setLoading(true);
    setError(null);
    try {
      await beginOidcRedirect({ returnPath: "/dashboard" });
    } catch (err) {
      setError(err);
      setLoading(false);
    }
  }

  async function handlePromote() {
    setLoading(true);
    setError(null);

    if (!session) {
      navigate("/signin", { replace: true });
      return;
    }

    try {
      const promoted = await promoteBootstrapKey(session);
      const nextSession = {
        ...session,
        authMode: "api_key" as const,
        tenantId: promoted.tenant_id,
        apiKey: promoted.api_key,
        keyId: promoted.key_id,
        phase: "operational" as const,
      };
      saveSession(nextSession);
      refreshSession();

      let orgName: string | undefined;
      let slug: string | undefined;

      try {
        const account = await getAccountMe(nextSession);
        orgName = account.tenant.name;
        slug = account.tenant.slug;
        saveSession({
          ...nextSession,
          email: account.membership?.email ?? account.principal.email ?? session.email,
          orgName,
          slug,
          plan: account.tenant.plan,
        });
        refreshSession();
      } catch {
        // Account reads are best-effort after promotion.
      }

      refreshSession();
      setActivated({
        tenantId: promoted.tenant_id,
        apiKey: promoted.api_key,
        orgName,
        slug,
      });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  if (activated) {
    return (
      <main className="page-shell narrow">
        <section className="panel auth-panel">
          <p className="eyebrow">Account activated</p>
          <h1>Save your sign-in credentials</h1>
          <p>
            This is the only time your operational API key is shown. Copy both values now so you can sign
            back in at <Link to="/signin">/signin</Link> after closing the browser.
          </p>

          <div className="warning-banner">
            Staging only: treat these credentials as temporary. Generate fresh API keys before go-live.
          </div>

          <div className="credential-grid">
            <div className="credential-field">
              <span className="credential-label">Tenant ID</span>
              <code className="credential-value">{activated.tenantId}</code>
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleCopy("tenant", activated.tenantId)}
              >
                {copiedField === "tenant" ? "Copied" : "Copy tenant ID"}
              </button>
            </div>

            <div className="credential-field">
              <span className="credential-label">API key</span>
              <code className="credential-value">{activated.apiKey}</code>
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleCopy("apiKey", activated.apiKey)}
              >
                {copiedField === "apiKey" ? "Copied" : "Copy API key"}
              </button>
            </div>
          </div>

          {activated.orgName ? (
            <p className="muted">
              Workspace <strong>{activated.orgName}</strong>
              {activated.slug ? (
                <>
                  {" "}
                  · slug <strong>{activated.slug}</strong>
                </>
              ) : null}
            </p>
          ) : null}

          <div className="button-row">
            <button type="button" onClick={() => navigate("/dashboard")}>
              Continue to dashboard
            </button>
            <Link className="ghost-link" to="/signin">
              Sign-in page
            </Link>
          </div>
        </section>
      </main>
    );
  }

  if (!session || isOperational(session)) {
    return null;
  }

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">One more step</p>
        <h1>Activate your account</h1>
        <p>
          Choose how you want to access Ajenda. Human users should sign in with Google. API keys are for
          machines, scripts, and integrations.
        </p>

        {oidcEnabled ? (
          <div className="form-grid">
            <OidcProviderButton
              provider={config.provider}
              loading={loading}
              onClick={() => void handleGoogleSignIn()}
              label="Continue with Google"
            />
            <p className="muted">Recommended for people using the dashboard, billing, and tasks UI.</p>
          </div>
        ) : null}

        <details className="staging-signin" open={!oidcEnabled}>
          <summary>Activate operational API key (machines)</summary>
          <ul className="checklist">
            <li>Bootstrap key expires automatically</li>
            <li>Promotion revokes the bootstrap key</li>
            <li>Operational key keeps dashboard and billing access</li>
            <li>You will copy tenant ID + API key once for automation sign-in</li>
          </ul>
          <button type="button" className="ghost-button" onClick={() => void handlePromote()} disabled={loading}>
            {loading ? "Activating..." : "Activate operational API key"}
          </button>
        </details>
      </section>

      <PageErrorAlert error={error} />
    </main>
  );
}