import { FormEvent, useState } from "react";
import { Link } from "react-router";
import { resendVerification } from "../api/client";
import type { ApiFailure } from "../types";
import { failureText } from "../utils/errors";

interface VerificationHelpPanelProps {
  initialEmail?: string;
  introText?: string;
  /** When set, verify-now invokes this handler instead of linking to /verify-email */
  onVerifyNow?: (token: string) => void;
  disabled?: boolean;
}

function isAlreadyVerifiedError(error: unknown): boolean {
  const failure = error as Partial<ApiFailure>;
  if (failure.status !== 404) {
    return false;
  }
  const body = failure.body;
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return false;
  }
  const detail = String((body as { detail: unknown }).detail).toLowerCase();
  return detail.includes("no pending verification") || detail.includes("already verified");
}

export default function VerificationHelpPanel({
  initialEmail = "",
  introText,
  onVerifyNow,
  disabled = false,
}: VerificationHelpPanelProps) {
  const [email, setEmail] = useState(initialEmail);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [alreadyVerified, setAlreadyVerified] = useState(false);

  async function handleResend(event?: FormEvent) {
    event?.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Enter your signup email to resend verification.");
      return;
    }

    setLoading(true);
    setError("");
    setNotice("");
    setAlreadyVerified(false);
    setToken(null);

    try {
      const response = await resendVerification(normalizedEmail);
      setEmail(response.email);
      if (response.verification_token) {
        setToken(response.verification_token);
        setNotice("Local staging exposes the verification token below — no real email is sent.");
      } else {
        setNotice(`Verification email resent to ${response.email}. Check your inbox for the link.`);
      }
    } catch (err) {
      if (isAlreadyVerifiedError(err)) {
        setAlreadyVerified(true);
        setError("");
      } else {
        setError(failureText(err));
      }
    } finally {
      setLoading(false);
    }
  }

  const verifyHref =
    token && email.trim()
      ? `/verify-email?email=${encodeURIComponent(email.trim())}&token=${encodeURIComponent(token)}`
      : token
        ? `/verify-email?token=${encodeURIComponent(token)}`
        : "/verify-email";

  return (
    <div className="form-grid">
      {introText ? <p className="muted">{introText}</p> : null}

      {alreadyVerified ? (
        <p className="muted">
          This email looks already verified.{" "}
          <Link to="/signin">Sign in</Link> with Google or an API key to continue.
        </p>
      ) : null}

      <form
        className="form-grid"
        onSubmit={(event) => {
          void handleResend(event);
        }}
      >
        <label>
          Signup email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            spellCheck={false}
            disabled={disabled || loading}
          />
        </label>
        <button
          type="submit"
          className="ghost-button"
          disabled={disabled || loading || !email.trim()}
        >
          {loading ? "Sending..." : "Resend verification"}
        </button>
      </form>

      {notice ? <p className="muted">{notice}</p> : null}

      {import.meta.env.DEV && token ? (
        <div className="callout">
          <p className="muted">
            Local staging does not send real email (<code>AJENDA_EMAIL_PROVIDER=noop</code>).
          </p>
          {onVerifyNow ? (
            <button type="button" onClick={() => onVerifyNow(token)} disabled={disabled || loading}>
              Verify email now
            </button>
          ) : (
            <Link className="primary-link" to={verifyHref}>
              Verify email now
            </Link>
          )}
        </div>
      ) : null}

      {!import.meta.env.DEV && token && onVerifyNow ? (
        <button type="button" onClick={() => onVerifyNow(token)} disabled={disabled || loading}>
          Verify email now
        </button>
      ) : null}

      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </div>
  );
}