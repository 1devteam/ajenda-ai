import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { getAccountMe, passwordLogin } from "../api/client";
import { beginOidcRedirect, oidcOriginWarning, oidcRedirectUri } from "../auth/oidc";
import { parseApiKeyHeader, saveSession, sessionFromPasswordResponse } from "../auth/session";
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const expiredNotice = useMemo(() => resolveExpiredNotice(searchParams), [searchParams]);
  const originWarning = useMemo(() => oidcOriginWarning(), []);

  useEffect(() => {
    resetForcedSignOutGuard();
  }, []);

  async function handleOidcSignIn() {
    setLoading(true);
    setError("");
    try {
      // Fail loud in the UI when origin is a Vite docker/LAN IP — Google will not accept it.
      const warning = oidcOriginWarning();
      if (warning) {
        setError(`${warning}\n\nWould send redirect_uri=${oidcRedirectUri()}`);
        setLoading(false);
        return;
      }
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

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await passwordLogin({ email: email.trim(), password });
      saveSession(sessionFromPasswordResponse(response));
      clearSignInNotice();
      navigate(returnPath.startsWith("/") ? returnPath : "/dashboard", { replace: true });
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell narrow auth-page-shell">
      <section className="panel auth-panel auth-panel-clean">
        <Link className="auth-brand" to="/" aria-label="Ajenda AI home">
          ajenda-ai
        </Link>

        <header className="auth-heading">
          <p className="eyebrow">Welcome back</p>
          <h1>Sign in to your workspace</h1>
          <p className="auth-lead">
            Sign in with your email and password.
          </p>
        </header>

        {expiredNotice ? (
          <div className="inline-error" role="alert">
            <strong>Session expired</strong>
            <pre>{expiredNotice}</pre>
          </div>
        ) : null}

        <form className="form-grid auth-primary-actions" onSubmit={(event) => void handlePasswordSubmit(event)}>
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          <button type="submit" disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button>
        </form>

        {oidcEnabled ? (
          <div className="form-grid auth-primary-actions">
            {originWarning ? (
              <div className="callout" role="status">
                <p className="muted">{originWarning}</p>
              </div>
            ) : null}
            <OidcProviderButton
              provider={config.provider}
              loading={loading}
              onClick={() => void handleOidcSignIn()}
            />
            <p className="muted auth-hint">
              Google sign-in is optional. Use it only if you connected Google identity to this workspace. Local Google login: open{" "}
              <code>http://localhost:5173</code> only — not Vite Network IPs.
            </p>
          </div>
        ) : (
          <OidcUnavailableNotice />
        )}

        <p className="auth-account-prompt">
          New to Ajenda AI? <Link to="/signup">Create an account</Link>
        </p>

        <details className="auth-more-options">
          <summary>More sign-in options</summary>
          <div className="auth-more-content">
            <section className="auth-option-section">
              <h2>Account verification</h2>
              <VerificationHelpPanel
                introText="Resend your verification email or finish verifying an existing account."
                onVerifyNow={(verifyToken) => {
                  navigate(`/verify-email?token=${encodeURIComponent(verifyToken)}`);
                }}
                disabled={loading}
              />
            </section>

            <section className="auth-option-section">
              <h2>Developer access</h2>
              <p className="muted">Use an API key for machine and automation access.</p>
              <form className="form-grid" onSubmit={(event) => void handleApiKeySubmit(event)}>
                <label>
                  Tenant ID
                  <input
                    value={tenantId}
                    onChange={(event) => setTenantId(event.target.value)}
                    placeholder="Tenant ID"
                    required
                    spellCheck={false}
                  />
                </label>
                <label>
                  API key
                  <input
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder="key_id.secret"
                    required
                    spellCheck={false}
                    autoComplete="off"
                  />
                </label>
                <button type="submit" className="ghost-button" disabled={loading}>
                  {loading ? "Signing in..." : "Sign in with API key"}
                </button>
              </form>
            </section>
          </div>
        </details>

        <p className="muted auth-legal">
          By continuing, you agree to our <Link to="/terms">Terms</Link> and{" "}
          <Link to="/privacy">Privacy Policy</Link>.
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
