import { Link, useLocation } from "react-router-dom";

export type NavItem = {
  to: string;
  label: string;
  icon: string;
  match?: string[];
};

export const COMMAND_CENTER_NAV: NavItem[] = [
  { to: "/dashboard", label: "Command Center", icon: "◆", match: ["/dashboard"] },
  { to: "/missions", label: "Launch Mission", icon: "▶", match: ["/missions", "/launch"] },
  { to: "/active-work", label: "Active Work", icon: "◎", match: ["/active-work", "/tasks"] },
  { to: "/approvals", label: "Approvals", icon: "!", match: ["/approvals"] },
  { to: "/results", label: "Results / Evidence", icon: "▣", match: ["/results", "/records"] },
  { to: "/business", label: "Business Memory", icon: "◈", match: ["/business"] },
  { to: "/connections", label: "Connections", icon: "⬡", match: ["/connections", "/credentials"] },
  { to: "/billing", label: "Billing", icon: "$", match: ["/billing"] },
  { to: "/settings", label: "Settings", icon: "⚙", match: ["/settings"] },
];

function isActive(pathname: string, item: NavItem): boolean {
  const prefixes = item.match ?? [item.to];
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

type SidebarNavProps = {
  className?: string;
  onNavigate?: () => void;
};

export default function SidebarNav({ className = "", onNavigate }: SidebarNavProps) {
  const location = useLocation();

  return (
    <nav className={`cc-nav ${className}`.trim()}>
      {COMMAND_CENTER_NAV.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          className={isActive(location.pathname, item) ? "cc-nav-link active" : "cc-nav-link"}
          onClick={onNavigate}
        >
          <span className="cc-nav-icon" aria-hidden>
            {item.icon}
          </span>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}