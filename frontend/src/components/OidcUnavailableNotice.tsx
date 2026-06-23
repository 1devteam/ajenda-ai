export default function OidcUnavailableNotice() {
  return (
    <div className="callout">
      <p className="muted">
        Google sign-in is not configured in this environment. Ask your operator to set{" "}
        <code>AJENDA_OIDC_LOGIN_ENABLED</code> with Google OAuth credentials, or use API-key sign-in
        below for staging.
      </p>
    </div>
  );
}