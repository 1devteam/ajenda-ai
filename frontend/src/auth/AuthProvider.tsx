import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { loadOidcConfig } from "./oidc";
import { loadSession, SESSION_CHANGED_EVENT, SESSION_STORAGE_KEY } from "./session";
import type { CustomerSession, OidcConfigResponse } from "../types";

const DISABLED_OIDC_CONFIG: OidcConfigResponse = {
  enabled: false,
  provider: "generic",
  client_id: null,
  authorization_endpoint: null,
  scopes: "openid email profile",
};

interface AuthContextValue {
  session: CustomerSession | null;
  oidcConfig: OidcConfigResponse;
  oidcEnabled: boolean;
  oidcLoading: boolean;
  refreshSession: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<CustomerSession | null>(() => loadSession());
  const [oidcConfig, setOidcConfig] = useState<OidcConfigResponse>(DISABLED_OIDC_CONFIG);
  const [oidcLoading, setOidcLoading] = useState(true);

  const refreshSession = useCallback(() => {
    setSession(loadSession());
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchOidcConfig() {
      try {
        const next = await loadOidcConfig();
        if (!cancelled) {
          setOidcConfig(next);
        }
      } catch {
        if (!cancelled) {
          setOidcConfig(DISABLED_OIDC_CONFIG);
        }
      } finally {
        if (!cancelled) {
          setOidcLoading(false);
        }
      }
    }

    void fetchOidcConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key === SESSION_STORAGE_KEY || event.key === null) {
        refreshSession();
      }
    }

    function handleSessionChanged() {
      refreshSession();
    }

    window.addEventListener("storage", handleStorage);
    window.addEventListener(SESSION_CHANGED_EVENT, handleSessionChanged);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener(SESSION_CHANGED_EVENT, handleSessionChanged);
    };
  }, [refreshSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      oidcConfig,
      oidcEnabled: oidcConfig.enabled,
      oidcLoading,
      refreshSession,
    }),
    [session, oidcConfig, oidcLoading, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}