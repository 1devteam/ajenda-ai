import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { signup } from "../api/client";
import VerificationHelpPanel from "../components/VerificationHelpPanel";
import { failureText } from "../utils/errors";

export default function SignupPage() {
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [slug, setSlug] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await signup({
        org_name: orgName.trim(),
        email: email.trim(),
        slug: slug.trim() || undefined,
        password,
      });
      if (response.status === "active") {
        navigate("/signin", { replace: true });
      } else {
        setPendingEmail(response.email);
      }
    } catch (err) {
      setError(failureText(err));
    } finally {
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
            Account created for <strong>{pendingEmail}</strong>. Verify your email to finish activation.
          </p>

          <VerificationHelpPanel
            initialEmail={pendingEmail}
            introText="Resend verification or use the staging token below to finish activation."
            onVerifyNow={(verifyToken) => {
              navigate(`/verify-email?email=${encodeURIComponent(pendingEmail)}&token=${encodeURIComponent(verifyToken)}`);
            }}
            disabled={loading}
          />

          <p className="muted">
            After verification, return to <Link to="/signin">Sign in</Link> with your email and password.
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

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">Get started</p>
        <h1>
          Create your <span className="brand-inline">ajenda-ai</span> workspace
        </h1>
        <p className="auth-lead">
          Create your workspace with a work email and password. Google is optional and only used for identity; Gmail, Calendar, and Contacts are connected later under Connections.
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
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} autoComplete="new-password" required />
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
