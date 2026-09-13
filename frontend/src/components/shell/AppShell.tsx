import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { useAuth } from "../../auth/AuthProvider";
import BrandMark from "../BrandMark";
import CommandCenterSidebar from "./CommandCenterSidebar";
import Button from "../primitives/Button";
import { UI_BUILD_ID } from "../../config/build";

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
        <div
          className="pointer-events-none fixed right-3 top-3 z-40 rounded-full border border-os-border bg-os-surface/95 px-2.5 py-1 font-mono text-[10px] font-medium tracking-wide text-os-muted shadow-sm backdrop-blur"
          title={`Ajenda frontend build ${UI_BUILD_ID}`}
          aria-label={`Ajenda frontend build ${UI_BUILD_ID}`}
        >
          UI build {UI_BUILD_ID}
        </div>
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-os-border bg-os-surface/95 px-4 backdrop-blur lg:hidden">
          <Button
            variant="ghost"
            className="min-h-10 min-w-10 px-2"
            aria-label="Open navigation"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <BrandMark to="/dashboard" compact />
        </header>

        <main className="flex-1 px-4 py-5 @md:px-6 @lg:px-8 @lg:py-8">{children}</main>
      </div>
    </div>
  );
}
