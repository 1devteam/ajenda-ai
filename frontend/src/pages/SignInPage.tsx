import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { getAccountMe } from "../api/client";
import { beginOidcRedirect } from "../auth/oidc";
import { parseApiKeyHeader, saveSession } from "../auth/session";
import OidcProviderButton from "../components/OidcProviderButton";
import OidcUnavailableNotice from "../components/OidcUnavailableNotice";
import VerificationHelpPanel from "../components/VerificationHelpPanel";
import { useAuth } from "../auth/AuthProvider";
import {
  clearSignInNotice,
  defaultSignInNotice,
  readSignInNotice,
  resetForcedSignOutGuard,
  type SessionSignOutReason,
} from "../auth/sessionLifecycle";
import { failureText } from "../utils/errors";

function resolveExpiredNotice(searchParams: URLSearchParams): string | null {
  const stored = readSignInNotice();
  if (stored?.message) {
    return stored.message;
  }
  const reason = searchParams.get("reason") as SessionSignOutReason | null;
  if (!reason) {
    return null;
  }
  return defaultSignInNotice(reason);
}

export default function SignInPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnPath = searchParams.get("return")?.trim() || "/dashboard";
  const { oidcConfig: config, oidcEnabled } = useAuth();
  const [tenantId, setTenantId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const expiredNotice = useMemo(() => resolveExpiredNotice(searchParams), [searchParams]);

  useEffect(() => {
    resetForcedSignOutGuard();
  }, []);

  async function handleOidcSignIn() {
    setLoading(true);
    setError("");
    try {
      await beginOidcRedirect({ returnPath });
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
      clearSignInNotice();
      navigate(returnPath.startsWith("/") ? returnPath : "/dashboard", { replace: true });
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
        <h1>
          Sign in to <span className="brand-inline">ajenda-ai</span>
        </h1>
        <p className="auth-lead">
          Use Google to access your workspace. API keys remain available below for machine and
          automation use.
        </p>

        {expiredNotice ? (
          <div className="inline-error" role="alert">
            <strong>Session expired</strong>
            <pre>{expiredNotice}</pre>
          </div>
        ) : null}

        {oidcEnabled ? (
          <div className="form-grid auth-primary-actions">
            <OidcProviderButton
              provider={config.provider}
              loading={loading}
              onClick={() => void handleOidcSignIn()}
            />
            <p className="muted auth-hint">
              Your Google email must match the address you used to create and verify your account.
              Use <strong>{window.location.origin}</strong> consistently when signing in locally.
            </p>
          </div>
        ) : (
          <OidcUnavailableNotice />
        )}

        <details className="staging-signin">
          <summary>Email not verified yet?</summary>
          <VerificationHelpPanel
            introText={
              "Google sign-in requires a verified account. Resend verification, then finish at /verify-email."
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

        <p className="muted auth-footer">
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
