import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthProvider";
import SidebarNav from "./SidebarNav";

type AppShellProps = {
  children: ReactNode;
  orgName?: string;
  plan?: string;
  email?: string;
  tenantStatus?: string;
  onSignOut: () => void;
};

export default function AppShell({
  children,
  orgName,
  plan,
  email,
  tenantStatus,
  onSignOut,
}: AppShellProps) {
  const { session } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const online = tenantStatus === "active";

  return (
    <div className="cc-shell">
      <aside className={`cc-sidebar${sidebarOpen ? " open" : ""}`}>
        <div className="cc-sidebar-brand">
          <Link to="/dashboard" onClick={() => setSidebarOpen(false)}>
            ajenda-ai
          </Link>
          <span>Autonomous business OS</span>
        </div>

        <SidebarNav onNavigate={() => setSidebarOpen(false)} />

        <div className="cc-sidebar-footer">
          <div className="cc-user-card">
            <strong>{orgName ?? session?.orgName ?? "Workspace"}</strong>
            <small>
              {email ?? session?.tenantId.slice(0, 8)}
              {plan ? ` · ${plan}` : ""}
            </small>
          </div>
          <div className="cc-system-status">
            <span className={`status-dot ${online ? "ok" : ""}`} />
            {online ? "System online" : "Setup in progress"}
          </div>
          <button type="button" className="ghost-button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="cc-main">
        <header className="cc-topbar">
          <button
            type="button"
            className="cc-mobile-menu-btn"
            aria-label="Open navigation"
            onClick={() => setSidebarOpen((open) => !open)}
          >
            ☰
          </button>
          <strong>ajenda-ai</strong>
        </header>
        <div className="cc-main-inner">{children}</div>
      </div>
    </div>
  );
}