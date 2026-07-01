import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAccountMe } from "../api/client";
import { beginOidcRedirect } from "../auth/oidc";
import { parseApiKeyHeader, saveSession } from "../auth/session";
import OidcProviderButton from "../components/OidcProviderButton";
import OidcUnavailableNotice from "../components/OidcUnavailableNotice";
import VerificationHelpPanel from "../components/VerificationHelpPanel";
import { useAuth } from "../auth/AuthProvider";
import { failureText } from "../utils/errors";

export default function SignInPage() {
  const navigate = useNavigate();
  const { oidcConfig: config, oidcEnabled } = useAuth();
  const [tenantId, setTenantId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleOidcSignIn() {
    setLoading(true);
    setError("");
    try {
      await beginOidcRedirect({ returnPath: "/dashboard" });
    } catch (err) {
      setError(failureText(err));
      setLoading(false);
    }
  }

  async function handleApiKeySubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const normalizedTenantId = tenantId.trim();
    if (!normalizedTenantId) {
      setError("Tenant ID is required. Copy it from signup verification or the /promote activation screen.");
      setLoading(false);
      return;
    }

    const parsedKey = parseApiKeyHeader(apiKey);
    if (!parsedKey) {
      setError("API key must use the key_id.secret format.");
      setLoading(false);
      return;
    }

    const candidate = {
      authMode: "api_key" as const,
      tenantId: normalizedTenantId,
      apiKey: parsedKey.apiKey,
      keyId: parsedKey.keyId,
      phase: "operational" as const,
    };

    try {
      const account = await getAccountMe(candidate);
      saveSession({
        ...candidate,
        email: account.membership?.email ?? account.principal.email ?? undefined,
        orgName: account.tenant.name,
        slug: account.tenant.slug,
        plan: account.tenant.plan,
      });
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">Welcome back</p>
        <h1>Sign in</h1>
        <p>
          Use Google to access your Ajenda workspace. API keys remain available below for machine and
          automation use.
        </p>

        {oidcEnabled ? (
          <div className="form-grid">
            <OidcProviderButton
              provider={config.provider}
              loading={loading}
              onClick={() => void handleOidcSignIn()}
            />
            <p className="muted">
              Your Google email must match the address you used to create and verify your Ajenda account.
              Use <strong>{window.location.origin}</strong> consistently (not 127.0.0.1) when signing in
              locally.
            </p>
          </div>
        ) : (
          <OidcUnavailableNotice />
        )}

        <details className="staging-signin">
          <summary>Email not verified yet?</summary>
          <VerificationHelpPanel
            introText={
              "Google sign-in requires a verified Ajenda account. Resend verification, then finish at /verify-email."
            }
            onVerifyNow={(verifyToken) => {
              navigate(`/verify-email?token=${encodeURIComponent(verifyToken)}`);
            }}
            disabled={loading}
          />
        </details>

        <details className="staging-signin">
          <summary>Machine sign-in (API key)</summary>
          <form className="form-grid" onSubmit={(event) => void handleApiKeySubmit(event)}>
            <label>
              Tenant ID
              <input
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
                placeholder="26f72911-6433-4ef4-bdcd-cc7609f9c254"
                required
                spellCheck={false}
              />
            </label>
            <label>
              API key
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="abcdefghijklmnopqrst.key_secret_part"
                required
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <button type="submit" className="ghost-button" disabled={loading}>
              {loading ? "Signing in..." : "Sign in with API key"}
            </button>
          </form>
        </details>

        <p className="muted">
          New here? <Link to="/signup">Create an account</Link>
        </p>
      </section>

      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}