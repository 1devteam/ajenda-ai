import AuthErrorAlert from "./AuthErrorAlert";

interface PageErrorAlertProps {
  error: unknown;
  className?: string;
}

export default function PageErrorAlert({ error, className = "inline-error" }: PageErrorAlertProps) {
  if (!error) {
    return null;
  }
  if (typeof error === "string") {
    return (
      <div className={className} role="alert">
        <pre>{error}</pre>
      </div>
    );
  }
  return <AuthErrorAlert error={error} className={className} />;
}