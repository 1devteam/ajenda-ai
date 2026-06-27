import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { logoutCustomer } from "../api/client";
import { clearSession, isOperational, loadSession } from "../auth/session";

const CUSTOMER_LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/missions", label: "Missions" },
  { to: "/tasks", label: "Tasks" },
  { to: "/credentials", label: "Credentials" },
  { to: "/billing", label: "Billing" },
] as const;

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const session = loadSession();
  const signedIn = session !== null;
  const operational = session !== null && isOperational(session);

  async function handleSignOut() {
    const current = loadSession();
    if (current?.authMode === "oidc") {
      try {
        await logoutCustomer(current);
      } catch {
        // Local session clear still proceeds on logout API failure.
      }
    }
    clearSession();
    navigate("/signin");
  }

  return (
    <div className="customer-shell">
      <header className="app-nav">
        <div className="brand">
          <Link to={signedIn ? "/dashboard" : "/signin"}>Ajenda AI</Link>
          <span className="brand-tag">Customer</span>
        </div>

        {signedIn ? (
          <nav className="nav-links">
            {CUSTOMER_LINKS.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className={location.pathname.startsWith(link.to) ? "active" : undefined}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        ) : null}

        <div className="nav-actions">
          {signedIn ? (
            <>
              <span className="session-pill">
                {session.slug ?? session.tenantId.slice(0, 8)}
                {operational ? "" : " · bootstrap"}
              </span>
              <button type="button" className="ghost-button" onClick={handleSignOut}>
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

      <Outlet />

      <footer className="app-footer">
        <span>Self-serve onboarding, billing, and runtime tasks.</span>
        <Link to="/dev">Runtime dev console</Link>
      </footer>
    </div>
  );
}