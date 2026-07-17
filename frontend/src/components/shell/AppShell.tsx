import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { useAuth } from "../../auth/AuthProvider";
import CommandCenterSidebar from "./CommandCenterSidebar";
import Button from "../primitives/Button";

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
  const [mobileOpen, setMobileOpen] = useState(false);
  const online = tenantStatus === "active";

  return (
    <div className="ajenda-os flex min-h-screen bg-os-bg">
      <CommandCenterSidebar
        orgName={orgName ?? session?.orgName}
        plan={plan ?? session?.plan}
        email={email ?? session?.email}
        tenantOnline={online}
        mobileOpen={mobileOpen}
        onNavigate={() => setMobileOpen(false)}
        onMobileClose={() => setMobileOpen(false)}
        onSignOut={onSignOut}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-os-border bg-os-surface/95 px-4 backdrop-blur lg:hidden">
          <Button
            variant="ghost"
            className="min-h-10 min-w-10 px-2"
            aria-label="Open navigation"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <span className="font-display text-base font-semibold">
            <span className="text-crimson">ajenda</span>-ai
          </span>
        </header>

        <main className="flex-1 px-4 py-5 @md:px-6 @lg:px-8 @lg:py-8">{children}</main>
      </div>
    </div>
  );
}
