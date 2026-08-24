import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { resendVerification, verifyEmail } from "../api/onboarding";
import { failureText } from "../utils/errors";

export default function VerifyEmailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const normalizedEmail = email.trim();
    const normalizedCode = code.trim();
    if (!normalizedEmail || !/^\d{6}$/.test(normalizedCode)) {
      setError("Enter your signup email and the six-digit verification code.");
      return;
    }

    setLoading(true);
    setError("");
    setNotice("");
    try {
      const response = await verifyEmail(normalizedEmail, normalizedCode);
      if (!response.tenant_id?.trim()) {
        throw new Error("Verification succeeded but the workspace identity was missing from the response.");
      }
      navigate(`/signin?verified=1&email=${encodeURIComponent(normalizedEmail)}`, { replace: true });
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Enter your signup email before requesting a new code.");
      return;
    }

    setResending(true);
    setError("");
    setNotice("");
    try {
      const response = await resendVerification(normalizedEmail);
      setEmail(response.email);
      if (response.verification_code && import.meta.env.DEV) {
        setCode(response.verification_code);
        setNotice(`Local staging verification code: ${response.verification_code}`);
      } else {
        setNotice(`If verification is pending for ${response.email}, a new code has been sent.`);
      }
    } catch (err) {
      setError(failureText(err));
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">Email verification</p>
        <h1>Verify your account</h1>
        <p>
          Enter the six-digit code Ajenda sent to your signup email. Your password account stays inactive until this step succeeds.
        </p>

        <form className="form-grid" onSubmit={(event) => void handleSubmit(event)}>
          <label>
            Signup email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="owner@example.com"
              autoComplete="email"
              required
            />
          </label>
          <label>
            Verification code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="123456"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              spellCheck={false}
            />
          </label>
          <button type="submit" disabled={loading || resending || !email.trim() || code.length !== 6}>
            {loading ? "Verifying..." : "Verify email"}
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void handleResend()}
            disabled={loading || resending || !email.trim()}
          >
            {resending ? "Sending..." : "Resend verification code"}
          </button>
        </form>

        {notice ? <p className="muted">{notice}</p> : null}

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
