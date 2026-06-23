import { useEffect, useState } from "react";
import { loadOidcConfig } from "../auth/oidc";
import type { OidcConfigResponse } from "../types";

const DISABLED_CONFIG: OidcConfigResponse = {
  enabled: false,
  provider: "generic",
  client_id: null,
  authorization_endpoint: null,
  scopes: "openid email profile",
};

export function useOidcConfig() {
  const [config, setConfig] = useState<OidcConfigResponse>(DISABLED_CONFIG);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchConfig() {
      try {
        const next = await loadOidcConfig();
        if (!cancelled) {
          setConfig(next);
        }
      } catch {
        if (!cancelled) {
          setConfig(DISABLED_CONFIG);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  return { config, loading, enabled: config.enabled };
}