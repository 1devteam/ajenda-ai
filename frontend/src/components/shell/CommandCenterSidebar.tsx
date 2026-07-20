import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, ChevronLeft, ChevronRight, LogOut, Settings, CreditCard, Menu } from "lucide-react";
import { COMMAND_CENTER_NAV, isNavItemActive } from "../../config/nav";
import BrandMark from "../BrandMark";
import Button from "../primitives/Button";

type CommandCenterSidebarProps = {
  orgName?: string;
  plan?: string;
  email?: string;
  tenantOnline?: boolean;
  mobileOpen?: boolean;
  onNavigate?: () => void;
  onSignOut: () => void;
  onMobileClose?: () => void;
};

export default function CommandCenterSidebar({
  orgName,
  plan,
  email,
  tenantOnline = true,
  mobileOpen = false,
  onNavigate,
  onSignOut,
  onMobileClose,
}: CommandCenterSidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [missionsOpen, setMissionsOpen] = useState(location.pathname.startsWith("/missions"));
  const accountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (!accountRef.current?.contains(event.target as Node)) {
        setAccountOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const sidebarWidth = collapsed ? "w-[72px]" : "w-[260px]";

  function go(path: string) {
    setAccountOpen(false);
    onNavigate?.();
    navigate(path);
  }

  const navContent = (
    <>
      <div
        className={`flex items-center border-b border-os-border px-3 py-4 ${
          collapsed ? "justify-center" : "justify-between"
        }`}
      >
        {!collapsed ? (
          <div className="min-w-0">
            <BrandMark to="/dashboard" onClick={onNavigate} />
            <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-500">
              Command center
            </p>
          </div>
        ) : (
          <BrandMark to="/dashboard" onClick={onNavigate} compact aria-label="ajenda-ai home" />
        )}
        <button
          type="button"
          className="cc-focus-ring hidden rounded-md border border-os-border p-1.5 text-zinc-400 hover:text-zinc-200 lg:inline-flex"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-3" aria-label="Primary">
        {COMMAND_CENTER_NAV.map((item) => {
          const active = isNavItemActive(location.pathname, item);
          const Icon = item.icon;
          const isMissions = item.to === "/missions";
          return (
            <div key={item.to}>
            <Link
              to={item.to}
              onClick={onNavigate}
              title={collapsed ? item.label : undefined}
              className={`cc-focus-ring group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-os-surface-elevated text-zinc-100"
                  : "text-zinc-400 hover:bg-os-surface-elevated/60 hover:text-zinc-200"
              }`}
            >
              {active ? (
                <span className="absolute bottom-2 left-0 top-2 w-1 rounded-r bg-brand-accent" aria-hidden />
              ) : null}
              <Icon className="h-4 w-4 shrink-0 opacity-90" aria-hidden />
              {!collapsed ? <span className="truncate">{item.label}</span> : null}
              {isMissions && !collapsed ? (
                <span
                  role="button"
                  tabIndex={0}
                  className="ml-auto rounded p-1 text-zinc-500 hover:text-zinc-200"
                  aria-label="Toggle mission navigation"
                  aria-expanded={missionsOpen}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setMissionsOpen((open) => !open);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setMissionsOpen((open) => !open);
                    }
                  }}
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${missionsOpen ? "rotate-180" : ""}`} />
                </span>
              ) : null}
            </Link>
            {isMissions && missionsOpen && !collapsed ? (
              <div className="cc-nav-children">
                <Link to="/missions" onClick={onNavigate}>New mission</Link>
                <Link to="/missions#running" onClick={onNavigate}>Running</Link>
                <Link to="/missions#staged" onClick={onNavigate}>Staged</Link>
                <Link to="/missions#history" onClick={onNavigate}>History</Link>
              </div>
            ) : null}
            </div>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 border-t border-os-border px-3 py-4" ref={accountRef}>
        <div className="flex items-center gap-2 text-xs text-zinc-400">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              tenantOnline ? "bg-semantic-success" : "bg-semantic-warning"
            }`}
            aria-hidden
          />
          {!collapsed ? (tenantOnline ? "System online" : "Setup in progress") : null}
        </div>

        <div className="relative">
          <button
            type="button"
            className={`cc-focus-ring flex w-full items-center gap-2 rounded-lg border border-os-border bg-os-surface-elevated px-3 py-2.5 text-left transition-colors hover:border-zinc-600 ${
              collapsed ? "justify-center px-2" : ""
            }`}
            aria-expanded={accountOpen}
            aria-haspopup="menu"
            onClick={() => setAccountOpen((open) => !open)}
          >
            <Menu className="h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
            {!collapsed ? (
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-zinc-100">
                  {orgName ?? "Workspace"}
                </span>
                <span className="block truncate text-xs text-zinc-500">
                  {email ?? "Account"}
                  {plan ? ` · ${plan}` : ""}
                </span>
              </span>
            ) : null}
          </button>

          {accountOpen ? (
            <div
              role="menu"
              className="absolute bottom-full left-0 z-50 mb-2 w-full min-w-[200px] rounded-lg border border-os-border bg-os-surface-elevated py-1 shadow-lift"
            >
              <button
                type="button"
                role="menuitem"
                className="cc-focus-ring flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-zinc-200 hover:bg-os-bg"
                onClick={() => go("/billing")}
              >
                <CreditCard className="h-4 w-4" aria-hidden />
                Billing
              </button>
              <button
                type="button"
                role="menuitem"
                className="cc-focus-ring flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-zinc-200 hover:bg-os-bg"
                onClick={() => go("/settings")}
              >
                <Settings className="h-4 w-4" aria-hidden />
                Settings
              </button>
              <div className="my-1 border-t border-os-border" />
              <button
                type="button"
                role="menuitem"
                className="cc-focus-ring flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-zinc-200 hover:bg-os-bg"
                onClick={() => {
                  setAccountOpen(false);
                  onSignOut();
                }}
              >
                <LogOut className="h-4 w-4" aria-hidden />
                Sign out
              </button>
            </div>
          ) : null}
        </div>

        {collapsed ? (
          <Button variant="ghost" className="w-full min-h-10 px-2" onClick={onSignOut} aria-label="Sign out">
            <LogOut className="h-4 w-4" />
          </Button>
        ) : null}
      </div>
    </>
  );

  return (
    <>
      {mobileOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
          aria-label="Close navigation"
          onClick={onMobileClose}
        />
      ) : null}

      <aside
        className={`ajenda-os fixed inset-y-0 left-0 z-50 flex shrink-0 flex-col border-r border-os-border bg-os-surface transition-transform duration-200 motion-reduce:transition-none lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:translate-x-0 ${sidebarWidth} ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {navContent}
      </aside>
    </>
  );
}
