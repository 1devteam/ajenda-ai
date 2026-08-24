import { FormEvent, useState } from "react";
import { Link } from "react-router";
import { resendVerification } from "../api/onboarding";
import { failureText } from "../utils/errors";

interface VerificationHelpPanelProps {
  initialEmail?: string;
  initialCode?: string | null;
  introText?: string;
  onVerifyNow?: (code: string) => void;
  disabled?: boolean;
}

export default function VerificationHelpPanel({
  initialEmail = "",
  initialCode = null,
  introText,
  onVerifyNow,
  disabled = false,
}: VerificationHelpPanelProps) {
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState<string | null>(initialCode);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
    setCode(null);

    try {
      const response = await resendVerification(normalizedEmail);
      setEmail(response.email);
      if (response.verification_code && import.meta.env.DEV) {
        setCode(response.verification_code);
        setNotice("Local staging exposes the verification code below — no real email is required.");
      } else {
        setNotice(`If verification is pending for ${response.email}, a new code has been sent.`);
      }
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  const verifyHref = email.trim()
    ? `/verify-email?email=${encodeURIComponent(email.trim())}`
    : "/verify-email";

  return (
    <div className="form-grid">
      {introText ? <p className="muted">{introText}</p> : null}

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
          {loading ? "Sending..." : "Resend verification code"}
        </button>
      </form>

      {notice ? <p className="muted">{notice}</p> : null}

      {import.meta.env.DEV && code ? (
        <div className="callout">
          <p className="muted">
            Local staging verification code: <strong>{code}</strong>
          </p>
          {onVerifyNow ? (
            <button type="button" onClick={() => onVerifyNow(code)} disabled={disabled || loading}>
              Verify email now
            </button>
          ) : (
            <Link className="primary-link" to={verifyHref}>
              Open verification form
            </Link>
          )}
        </div>
      ) : null}

      {!code ? (
        <p className="muted">
          Have a code already? <Link to={verifyHref}>Enter verification code</Link>
        </p>
      ) : null}

      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </div>
  );
}
