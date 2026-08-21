import type { CustomerSession, RuntimeConfig } from "../types";

export const SESSION_STORAGE_KEY = "ajenda.customer.session.v1";
export const SESSION_CHANGED_EVENT = "ajenda:session-changed";

const SESSION_KEY = SESSION_STORAGE_KEY;

export function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
}

function normalizeSession(parsed: Record<string, unknown>): CustomerSession | null {
  const tenantId = String(parsed.tenantId ?? parsed.tenant_id ?? "").trim();
  const authMode = parsed.authMode === "oidc" ? "oidc" : "api_key";
  const phase = parsed.phase === "bootstrap" ? "bootstrap" : "operational";

  if (!tenantId) {
    return null;
  }

  if (authMode === "oidc") {
    const accessToken = String(parsed.accessToken ?? parsed.access_token ?? "").trim();
    if (!accessToken) {
      return null;
    }
    return {
      authMode: "oidc",
      tenantId,
      phase: "operational",
      accessToken,
      refreshToken:
        typeof parsed.refreshToken === "string"
          ? parsed.refreshToken
          : typeof parsed.refresh_token === "string"
            ? parsed.refresh_token
            : undefined,
      expiresAt:
        typeof parsed.expiresAt === "string"
          ? parsed.expiresAt
          : typeof parsed.expires_at === "string"
            ? parsed.expires_at
            : undefined,
      refreshExpiresAt:
        typeof parsed.refreshExpiresAt === "string"
          ? parsed.refreshExpiresAt
          : typeof parsed.refresh_expires_at === "string"
            ? parsed.refresh_expires_at
            : undefined,
      email: typeof parsed.email === "string" ? parsed.email : undefined,
      orgName: typeof parsed.orgName === "string" ? parsed.orgName : undefined,
      slug: typeof parsed.slug === "string" ? parsed.slug : undefined,
      plan: typeof parsed.plan === "string" ? parsed.plan : undefined,
    };
  }

  const apiKey = String(parsed.apiKey ?? parsed.api_key ?? "").trim();
  const keyId = String(parsed.keyId ?? parsed.key_id ?? "").trim();
  if (!apiKey || !keyId) {
    return null;
  }

  return {
    authMode: "api_key",
    tenantId,
    apiKey,
    keyId,
    phase,
    email: typeof parsed.email === "string" ? parsed.email : undefined,
    orgName: typeof parsed.orgName === "string" ? parsed.orgName : undefined,
    slug: typeof parsed.slug === "string" ? parsed.slug : undefined,
    plan: typeof parsed.plan === "string" ? parsed.plan : undefined,
  };
}

export function loadSession(): CustomerSession | null {
  const raw = window.sessionStorage.getItem(SESSION_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return normalizeSession(parsed);
  } catch {
    return null;
  }
}

export function requireSession(): CustomerSession {
  const session = loadSession();
  if (!session) {
    throw new Error("No active customer session. Sign in or complete onboarding.");
  }
  return session;
}

function notifySessionChanged(): void {
  window.dispatchEvent(new Event(SESSION_CHANGED_EVENT));
}

export function saveSession(session: CustomerSession): void {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  notifySessionChanged();
}

export function clearSession(): void {
  window.sessionStorage.removeItem(SESSION_KEY);
  notifySessionChanged();
}

export function sessionToRuntimeConfig(session: CustomerSession): RuntimeConfig {
  return {
    apiBaseUrl: getApiBaseUrl(),
    tenantId: session.tenantId,
    apiKey: session.apiKey ?? "",
    accessToken: session.accessToken,
    authMode: session.authMode,
  };
}

export function isOperational(session: CustomerSession): boolean {
  return session.authMode === "oidc" || session.phase === "operational";
}

export function parseApiKeyHeader(value: string): { keyId: string; apiKey: string } | null {
  const trimmed = value.trim();
  const dot = trimmed.indexOf(".");
  if (dot <= 0 || dot === trimmed.length - 1) {
    return null;
  }

  return {
    keyId: trimmed.slice(0, dot),
    apiKey: trimmed,
  };
}

export { shouldRefreshAccessToken as isSessionNearExpiry } from "./sessionLifecycle";

export function sessionFromOidcResponse(response: {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in?: number;
  tenant_id: string;
  email: string;
  org_name: string;
  slug: string;
  plan: string;
}): CustomerSession {
  const now = Date.now();
  const expiresAt = new Date(now + response.expires_in * 1000).toISOString();
  const refreshExpiresAt =
    typeof response.refresh_expires_in === "number" && response.refresh_expires_in > 0
      ? new Date(now + response.refresh_expires_in * 1000).toISOString()
      : undefined;
  return {
    authMode: "oidc",
    tenantId: response.tenant_id,
    phase: "operational",
    accessToken: response.access_token,
    refreshToken: response.refresh_token,
    expiresAt,
    refreshExpiresAt,
    email: response.email,
    orgName: response.org_name,
    slug: response.slug,
    plan: response.plan,
  };
}

export const sessionFromPasswordResponse = sessionFromOidcResponse;
