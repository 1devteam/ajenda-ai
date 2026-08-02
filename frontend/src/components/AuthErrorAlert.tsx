import { Link } from "react-router";
import type { ApiFailure } from "../types";
import { authErrorDetails } from "../utils/errors";

interface AuthErrorAlertProps {
  error: unknown;
  className?: string;
}

export default function AuthErrorAlert({ error, className = "inline-error" }: AuthErrorAlertProps) {
  const details = authErrorDetails(error);
  const failure = error as Partial<ApiFailure>;

  return (
    <div className={className} role="alert">
      {details.title ? <strong>{details.title}</strong> : null}
      <pre>{details.message}</pre>
      {details.action ? (
        <Link className="primary-link" to={details.action.href}>
          {details.action.label}
        </Link>
      ) : null}
      {details.code && failure.status ? (
        <small className="muted">
          {failure.status} · {details.code}
        </small>
      ) : null}
    </div>
  );
}