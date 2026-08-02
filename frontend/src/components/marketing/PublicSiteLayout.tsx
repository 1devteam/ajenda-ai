import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { ArrowRight, Menu, X } from "lucide-react";
import { useAuth } from "../../auth/AuthProvider";
import { PUBLIC_SITE_NAV } from "../../config/marketingRoutes";
import BrandMark from "../BrandMark";

export default function PublicSiteLayout() {
  const { session } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [location.pathname]);

  return (
    <div className="marketing-site">
      <a className="marketing-skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="marketing-header">
        <div className="marketing-container marketing-nav-shell">
          <BrandMark to="/" className="marketing-wordmark" aria-label="Ajenda AI home" />

          <button
            type="button"
            className="marketing-menu-button"
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X aria-hidden /> : <Menu aria-hidden />}
          </button>

          <div className={`marketing-nav-panel ${menuOpen ? "is-open" : ""}`}>
            <nav className="marketing-nav-links" aria-label="Main navigation">
              {PUBLIC_SITE_NAV.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) => (isActive ? "is-active" : undefined)}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="marketing-nav-actions">
              <Link className="marketing-text-link" to={session ? "/dashboard" : "/signin"}>
                {session ? "Command center" : "Sign in"}
              </Link>
              <Link className="marketing-button marketing-button-small" to={session ? "/dashboard" : "/signup"}>
                {session ? "Open app" : "Start free"}
                <ArrowRight size={16} aria-hidden />
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main id="main-content">
        <Outlet />
      </main>

      <footer className="marketing-footer">
        <div className="marketing-container marketing-footer-grid">
          <div>
            <BrandMark to="/" className="marketing-wordmark" />
            <p>Governed AI work for businesses that need outcomes they can trust.</p>
          </div>
          <div className="marketing-footer-links" aria-label="Product links">
            <strong>Product</strong>
            <Link to="/product">How it works</Link>
            <Link to="/pricing">Pricing</Link>
            <Link to="/security">Security</Link>
          </div>
          <div className="marketing-footer-links" aria-label="Account links">
            <strong>Account</strong>
            <Link to="/signup">Start free</Link>
            <Link to="/signin">Sign in</Link>
          </div>
          <div className="marketing-footer-links" aria-label="Legal links">
            <strong>Legal</strong>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </div>
        </div>
        <div className="marketing-container marketing-footer-bottom">
          <span>© {new Date().getFullYear()} Ajenda AI. All rights reserved.</span>
          <span>Built for accountable execution.</span>
        </div>
      </footer>
    </div>
  );
}
