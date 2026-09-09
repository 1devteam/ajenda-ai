import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard,
  Rocket,
  ClipboardCheck,
  Activity,
  FileCheck2,
  Building2,
  Plug,
  Layers3,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  match?: string[];
};

/** Task-first primary nav. Billing/Settings live under account menu. */
export const COMMAND_CENTER_NAV: NavItem[] = [
  { to: "/dashboard", label: "Command Center", icon: LayoutDashboard, match: ["/dashboard"] },
  { to: "/missions", label: "Missions", icon: Rocket, match: ["/missions", "/launch"] },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck, match: ["/approvals"] },
  { to: "/active-work", label: "Active work", icon: Activity, match: ["/active-work", "/tasks"] },
  { to: "/results", label: "Outcomes", icon: FileCheck2, match: ["/results", "/records"] },
  { to: "/business", label: "Business memory", icon: Building2, match: ["/business"] },
  { to: "/connections", label: "Connections", icon: Plug, match: ["/connections", "/credentials"] },
  { to: "/vertical-ops", label: "Vertical operations", icon: Layers3, match: ["/vertical-ops"] },
];

export function isNavItemActive(pathname: string, item: NavItem): boolean {
  const prefixes = item.match ?? [item.to];
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
