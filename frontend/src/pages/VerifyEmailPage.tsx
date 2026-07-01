import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { verifyEmail } from "../api/client";
import { beginOidcRedirect } from "../auth/oidc";
import { saveSession } from "../auth/session";
import OidcProviderButton from "../components/OidcProviderButton";
import VerificationHelpPanel from "../components/VerificationHelpPanel";
import { useAuth } from "../auth/AuthProvider";
import { failureText } from "../utils/errors";

interface StoredBootstrapCredentials {
  tenantId: string;
  apiKey: string;
  keyId: string;
}

export default function VerifyEmailPage() {
  const navigate = useNavigate();
  const { oidcConfig: config, oidcEnabled, oidcLoading: configLoading } = useAuth();
  const [searchParams] = useSearchParams();
  const initialEmail = searchParams.get("email") ?? "";
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [autoAttempted, setAutoAttempted] = useState(false);
  const [verified, setVerified] = useState(false);
  const [bootstrapCredentials, setBootstrapCredentials] = useState<StoredBootstrapCredentials | null>(null);

  async function completeVerification(verificationToken: string) {
    setLoading(true);
    setError("");

    try {
      const response = await verifyEmail(verificationToken.trim());
      if (!response.tenant_id?.trim()) {
        throw new Error("Verification succeeded but tenant credentials were missing from the response.");
      }

      const credentials: StoredBootstrapCredentials = {
        tenantId: response.tenant_id.trim(),
        apiKey: response.api_key?.trim() ?? "",
        keyId: response.key_id?.trim() ?? "",
      };
      setBootstrapCredentials(credentials);

      if (oidcEnabled) {
        setVerified(true);
        return;
      }

      if (!credentials.apiKey || !credentials.keyId) {
        throw new Error("Verification succeeded but bootstrap credentials were missing from the response.");
      }

      saveSession({
        authMode: "api_key",
        tenantId: credentials.tenantId,
        apiKey: credentials.apiKey,
        keyId: credentials.keyId,
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

  function handleBootstrapFallback() {
    if (!bootstrapCredentials?.tenantId || !bootstrapCredentials.apiKey || !bootstrapCredentials.keyId) {
      setError("Bootstrap credentials are missing. Verify your email again to continue with an API key.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      saveSession({
        authMode: "api_key",
        tenantId: bootstrapCredentials.tenantId,
        apiKey: bootstrapCredentials.apiKey,
        keyId: bootstrapCredentials.keyId,
        phase: "bootstrap",
      });
      navigate("/promote", { replace: true });
    } catch (err) {
      setError(failureText(err));
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
              <button type="button" className="ghost-button" onClick={handleBootstrapFallback} disabled={loading}>
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
          Paste the verification token from your email link, or resend verification for your signup email.
          After verification you can sign in with Google using the same email address.
        </p>

        <VerificationHelpPanel
          initialEmail={initialEmail}
          introText="Resend verification for your signup email if you lost the link."
          onVerifyNow={(nextToken) => {
            setToken(nextToken);
            void completeVerification(nextToken);
          }}
          disabled={loading}
        />

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