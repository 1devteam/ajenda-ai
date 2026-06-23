import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { verifyEmail } from "../api/client";
import { beginOidcRedirect } from "../auth/oidc";
import { saveSession } from "../auth/session";
import OidcProviderButton from "../components/OidcProviderButton";
import { useOidcConfig } from "../hooks/useOidcConfig";
import { failureText } from "../utils/errors";

export default function VerifyEmailPage() {
  const navigate = useNavigate();
  const { config, enabled: oidcEnabled, loading: configLoading } = useOidcConfig();
  const [searchParams] = useSearchParams();
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [autoAttempted, setAutoAttempted] = useState(false);
  const [verified, setVerified] = useState(false);

  async function completeVerification(verificationToken: string) {
    setLoading(true);
    setError("");

    try {
      const response = await verifyEmail(verificationToken.trim());
      if (!response.tenant_id?.trim()) {
        throw new Error("Verification succeeded but tenant credentials were missing from the response.");
      }

      if (oidcEnabled) {
        setVerified(true);
        return;
      }

      if (!response.api_key?.trim() || !response.key_id?.trim()) {
        throw new Error("Verification succeeded but bootstrap credentials were missing from the response.");
      }

      saveSession({
        authMode: "api_key",
        tenantId: response.tenant_id.trim(),
        apiKey: response.api_key.trim(),
        keyId: response.key_id.trim(),
        phase: "bootstrap",
      });
      navigate("/promote", { replace: true });
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleActivation() {
    setLoading(true);
    setError("");
    try {
      await beginOidcRedirect({ returnPath: "/dashboard" });
    } catch (err) {
      setError(failureText(err));
      setLoading(false);
    }
  }

  async function handleBootstrapFallback() {
    const verificationToken = token.trim();
    if (!verificationToken) {
      setError("Verification token is required.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const response = await verifyEmail(verificationToken);
      saveSession({
        authMode: "api_key",
        tenantId: response.tenant_id.trim(),
        apiKey: response.api_key.trim(),
        keyId: response.key_id.trim(),
        phase: "bootstrap",
      });
      navigate("/promote", { replace: true });
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const queryToken = searchParams.get("token");
    if (!queryToken || autoAttempted || configLoading) {
      return;
    }
    setAutoAttempted(true);
    void completeVerification(queryToken);
  }, [autoAttempted, configLoading, oidcEnabled, searchParams]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await completeVerification(token);
  }

  if (verified) {
    return (
      <main className="page-shell narrow">
        <section className="panel auth-panel">
          <p className="eyebrow">Email verified</p>
          <h1>Finish setup with Google</h1>
          <p>
            Your workspace is active. Continue with Google to sign in as a human user. Use API keys later
            only for automation.
          </p>
          <div className="form-grid">
            <OidcProviderButton
              provider={config.provider}
              loading={loading}
              onClick={() => void handleGoogleActivation()}
            />
            <details className="staging-signin">
              <summary>Use bootstrap API key instead</summary>
              <button type="button" className="ghost-button" onClick={() => void handleBootstrapFallback()} disabled={loading}>
                Continue with API key activation
              </button>
            </details>
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

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">Email verification</p>
        <h1>Activate your workspace</h1>
        <p>
          Paste the verification token from your email link. After verification you can sign in with Google
          using the same email address.
        </p>

        <form className="form-grid" onSubmit={(event) => void handleSubmit(event)}>
          <label>
            Verification token
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="paste token from email URL"
              required
              spellCheck={false}
            />
          </label>
          <button type="submit" disabled={loading || !token.trim()}>
            {loading ? "Verifying..." : "Verify email"}
          </button>
        </form>

        <p className="muted">
          Already activated? <Link to="/signin">Sign in</Link>
        </p>
        <p className="muted">
          Need an account? <Link to="/signup">Sign up</Link>
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