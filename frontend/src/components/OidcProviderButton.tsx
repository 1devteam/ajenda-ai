import { providerLabel } from "../auth/oidc";

interface OidcProviderButtonProps {
  provider: string;
  loading?: boolean;
  disabled?: boolean;
  onClick: () => void;
  label?: string;
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18">
      <path
        fill="#EA4335"
        d="M12 10.2v3.6h5.1c-.2 1.2-1.5 3.5-5.1 3.5-3.1 0-5.6-2.5-5.6-5.6S8.9 5.1 12 5.1c1.8 0 3 .8 3.7 1.4l2.5-2.4C16.8 2.8 14.6 2 12 2 6.9 2 2.8 6.1 2.8 11.2S6.9 20.4 12 20.4c6.2 0 7.7-4.3 7.7-6.5 0-.4 0-.7-.1-1H12z"
      />
      <path
        fill="#34A853"
        d="M3.9 7.3 6.8 9.5C7.7 7.2 9.7 5.6 12 5.6c1.8 0 3 .8 3.7 1.4l2.5-2.4C16.8 2.8 14.6 2 12 2 8.2 2 4.9 4.2 3.9 7.3z"
      />
      <path fill="#4A90E2" d="M12 20.4c3.2 0 5.9-1.1 7.8-2.9l-3.6-2.8c-1 .7-2.3 1.1-4.2 1.1-3.1 0-5.6-2.5-5.6-5.6 0-.4.1-.8.2-1.2L3.9 7.3C2.8 9.2 2.2 11.5 2.2 14c0 3.5 1.4 6.6 3.7 8.9 1.5 1.5 3.5 2.5 6.1 2.5z" />
      <path fill="#FBBC05" d="M20.8 13.5c.1-.4.1-.8.1-1.2 0-1.2-.2-2.3-.6-3.3H12v3.6h5.1c-.4 1.1-1.2 2-2.3 2.6l3.6 2.8c2.1-1.9 3.4-4.7 3.4-8.1z" />
    </svg>
  );
}

export default function OidcProviderButton({
  provider,
  loading = false,
  disabled = false,
  onClick,
  label,
}: OidcProviderButtonProps) {
  const text =
    label ?? (loading ? "Redirecting..." : `Continue with ${providerLabel(provider)}`);
  const isGoogle = provider === "google";

  return (
    <button
      type="button"
      className={isGoogle ? "oidc-button google" : "oidc-button"}
      onClick={onClick}
      disabled={loading || disabled}
    >
      {isGoogle ? <GoogleMark /> : null}
      <span>{text}</span>
    </button>
  );
}