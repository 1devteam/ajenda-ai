import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { resendVerification, signup } from "../api/client";
import { beginOidcRedirect } from "../auth/oidc";
import OidcProviderButton from "../components/OidcProviderButton";
import { useOidcConfig } from "../hooks/useOidcConfig";
import { failureText } from "../utils/errors";

export default function SignupPage() {
  const navigate = useNavigate();
  const { config, enabled: oidcEnabled } = useOidcConfig();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [verifyToken, setVerifyToken] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await signup({
        org_name: orgName.trim(),
        email: email.trim(),
        slug: slug.trim() || undefined,
      });
      setPendingEmail(response.email);
      setVerifyToken(response.verification_token ?? null);
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    if (!pendingEmail) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await resendVerification(pendingEmail);
      if (response.verification_token) {
        setVerifyToken(response.verification_token);
      }
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifiedGoogleSignIn() {
    setLoading(true);
    setError("");
    try {
      await beginOidcRedirect({ returnPath: "/dashboard" });
    } catch (err) {
      setError(failureText(err));
      setLoading(false);
    }
  }

  if (pendingEmail) {
    return (
      <main className="page-shell narrow">
        <section className="panel auth-panel">
          <p className="eyebrow">Verify your email</p>
          <h1>Almost there</h1>
          <p>
            Account created for <strong>{pendingEmail}</strong>.
          </p>
          {verifyToken ? (
            <div className="callout">
              <p className="muted">
                Local staging does not send real email (<code>AJENDA_EMAIL_PROVIDER=noop</code>). Verify
                your email first, then sign in with Google using the same address.
              </p>
              <button
                type="button"
                onClick={() => navigate(`/verify-email?token=${encodeURIComponent(verifyToken)}`)}
              >
                Verify email now
              </button>
            </div>
          ) : (
            <p className="muted">
              Check your inbox for the verification link, or open{" "}
              <Link to="/verify-email">/verify-email</Link> and paste the token from the email URL.
            </p>
          )}
          {oidcEnabled ? (
            <div className="form-grid" style={{ marginTop: "1rem" }}>
              <p className="muted">Already verified? Continue with Google to open your workspace.</p>
              <OidcProviderButton
                provider={config.provider}
                loading={loading}
                onClick={() => void handleVerifiedGoogleSignIn()}
                label="Continue with Google after verification"
              />
            </div>
          ) : null}
          <div className="button-row">
            <button type="button" className="ghost-button" onClick={() => void handleResend()} disabled={loading}>
              Resend email
            </button>
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
        <p className="eyebrow">Get started</p>
        <h1>Create your workspace</h1>
        <p>
          Create your workspace with a work email. After verification, sign in with Google using the same
          address. API keys remain available for automation.
        </p>

        <form className="form-grid" onSubmit={(event) => void handleSubmit(event)}>
          <label>
            Organization name
            <input
              value={orgName}
              onChange={(event) => setOrgName(event.target.value)}
              placeholder="Acme Roofing"
              required
            />
          </label>
          <label>
            Work email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="owner@example.com"
              required
            />
          </label>
          <label>
            Slug (optional)
            <input
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              placeholder="acme-roofing"
              pattern="^[a-z0-9\-]+$"
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Creating..." : "Create account"}
          </button>
        </form>

        <p className="muted">
          Already have an account? <Link to="/signin">Sign in</Link>
        </p>
        <p className="muted">
          Still verifying? <Link to="/verify-email">Enter verification token</Link>
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