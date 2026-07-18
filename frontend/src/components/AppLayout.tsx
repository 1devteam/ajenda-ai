import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { logoutCustomer } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { clearSession, isOperational } from "../auth/session";
import { clearSignInNotice } from "../auth/sessionLifecycle";
import BrandMark from "./BrandMark";
import AppShell from "./shell/AppShell";

const PUBLIC_PATHS = new Set([
  "/signin",
  "/signup",
  "/verify-email",
  "/auth/callback",
  "/promote",
  "/dev",
]);

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { session } = useAuth();
  const signedIn = session !== null;
  const operational = session !== null && isOperational(session);
  const useCommandShell = signedIn && operational && !PUBLIC_PATHS.has(location.pathname);

  async function handleSignOut() {
    if (session?.authMode === "oidc") {
      try {
        await logoutCustomer(session);
      } catch {
        // Local session clear still proceeds on logout API failure.
      }
    }
    clearSignInNotice();
    clearSession();
    navigate("/signin");
  }

  if (useCommandShell) {
    return (
      <AppShell
        orgName={session?.orgName}
        plan={session?.plan}
        onSignOut={() => void handleSignOut()}
      >
        <Outlet />
      </AppShell>
    );
  }

  return (
    <div className="customer-shell">
      <header className="app-nav cc-public-nav">
        <div className="brand">
          <BrandMark to={signedIn ? "/dashboard" : "/signin"} />
          <span className="brand-tag">Customer</span>
        </div>

        <div className="nav-actions">
          {signedIn ? (
            <>
              <span className="session-pill">
                {session.slug ?? session.tenantId.slice(0, 8)}
                {session.plan ? ` · ${session.plan}` : ""}
                {operational ? "" : " · bootstrap"}
              </span>
              <button type="button" className="ghost-button" onClick={() => void handleSignOut()}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link className="primary-link" to="/signin">
                Sign in
              </Link>
              <Link className="ghost-link" to="/signup">
                Sign up
              </Link>
            </>
          )}
        </div>
      </header>

      <div className="cc-public-wrap">
        <Outlet />
      </div>
    </div>
  );
}