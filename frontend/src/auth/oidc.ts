import { getOidcConfig, startOidcLogin } from "../api/client";
import type { OidcConfigResponse } from "../types";
import { createCodeChallenge, createCodeVerifier } from "../utils/pkce";

export const PKCE_VERIFIER_KEY = "ajenda.oidc.code_verifier";
export const PKCE_PENDING_KEY = "ajenda.oidc.pending";
export const OIDC_RETURN_PATH_KEY = "ajenda.oidc.return_path";

interface PendingOidcLogin {
  verifier: string;
  returnPath?: string;
  createdAt: number;
}

export function oidcRedirectUri(): string {
  return `${window.location.origin}/auth/callback`;
}

/**
 * Google / OIDC redirect URIs are exact-match. Vite advertises every NIC as a
 * "Network" URL, but only origins registered in AJENDA_OIDC_REDIRECT_URI_ALLOWLIST
 * and Google Cloud Console work. Local dev defaults cover localhost/127.0.0.1 only.
 */
export function isOidcDevOriginAllowedByDefault(origin: string = window.location.origin): boolean {
  try {
    const url = new URL(origin);
    const host = url.hostname;
    const port = url.port || (url.protocol === "https:" ? "443" : "80");
    if (host !== "localhost" && host !== "127.0.0.1") {
      return false;
    }
    return port === "5173" || port === "8080" || port === "80" || port === "443";
  } catch {
    return false;
  }
}

export function oidcOriginWarning(origin: string = window.location.origin): string | null {
  if (isOidcDevOriginAllowedByDefault(origin)) {
    return null;
  }
  return (
    `You opened the app at ${origin}. Google sign-in only works from an origin registered ` +
    `exactly in AJENDA_OIDC_REDIRECT_URI_ALLOWLIST and Google Cloud Console (redirect = origin + /auth/callback). ` +
    `Vite's "Network" addresses (172.x / 10.x) are not registered. Use http://localhost:5173 for local Google login.`
  );
}

export function providerLabel(provider: string): string {
  if (provider === "google") {
    return "Google";
  }
  if (provider === "auth0") {
    return "Auth0";
  }
  return "your organization SSO";
}

function readPendingLogins(): Record<string, PendingOidcLogin> {
  const raw = window.sessionStorage.getItem(PKCE_PENDING_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, PendingOidcLogin>;
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function writePendingLogins(pending: Record<string, PendingOidcLogin>): void {
  window.sessionStorage.setItem(PKCE_PENDING_KEY, JSON.stringify(pending));
}

export function storePendingOidcLogin(loginIntentId: string, login: PendingOidcLogin): void {
  const pending = readPendingLogins();
  pending[loginIntentId] = login;
  writePendingLogins(pending);
  window.sessionStorage.setItem(PKCE_VERIFIER_KEY, login.verifier);
}

export function resolveCodeVerifier(loginIntentId: string | null): string | null {
  if (loginIntentId) {
    const pending = readPendingLogins()[loginIntentId];
    if (pending?.verifier) {
      return pending.verifier;
    }
  }
  return window.sessionStorage.getItem(PKCE_VERIFIER_KEY);
}

export function resolveReturnPath(loginIntentId: string | null): string | undefined {
  if (!loginIntentId) {
    return window.sessionStorage.getItem(OIDC_RETURN_PATH_KEY) ?? undefined;
  }
  return readPendingLogins()[loginIntentId]?.returnPath;
}

export async function loadOidcConfig(): Promise<OidcConfigResponse> {
  return getOidcConfig();
}

export async function beginOidcRedirect(options?: { returnPath?: string }): Promise<void> {
  const codeVerifier = createCodeVerifier();
  const codeChallenge = await createCodeChallenge(codeVerifier);

  const start = await startOidcLogin({
    redirect_uri: oidcRedirectUri(),
    code_challenge: codeChallenge,
  });

  storePendingOidcLogin(start.login_intent_id, {
    verifier: codeVerifier,
    returnPath: options?.returnPath,
    createdAt: Date.now(),
  });

  if (options?.returnPath) {
    window.sessionStorage.setItem(OIDC_RETURN_PATH_KEY, options.returnPath);
  } else {
    window.sessionStorage.removeItem(OIDC_RETURN_PATH_KEY);
  }

  window.location.assign(start.authorization_url);
}

export function clearOidcTransientState(loginIntentId?: string | null): void {
  window.sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  window.sessionStorage.removeItem(OIDC_RETURN_PATH_KEY);

  if (!loginIntentId) {
    window.sessionStorage.removeItem(PKCE_PENDING_KEY);
    return;
  }

  const pending = readPendingLogins();
  delete pending[loginIntentId];
  if (Object.keys(pending).length === 0) {
    window.sessionStorage.removeItem(PKCE_PENDING_KEY);
  } else {
    writePendingLogins(pending);
  }
}

export function consumeOidcReturnPath(loginIntentId?: string | null): string {
  const fromPending = resolveReturnPath(loginIntentId ?? null);
  if (fromPending?.startsWith("/")) {
    clearOidcTransientState(loginIntentId);
    return fromPending;
  }

  const path = window.sessionStorage.getItem(OIDC_RETURN_PATH_KEY);
  clearOidcTransientState(loginIntentId);
  return path?.startsWith("/") ? path : "/dashboard";
}

export function describeMissingCallbackParams(input: {
  code: string | null;
  loginIntentId: string | null;
  codeVerifier: string | null;
}): string {
  const missing: string[] = [];
  if (!input.code) {
    missing.push("authorization code");
  }
  if (!input.loginIntentId) {
    missing.push("state");
  }
  if (!input.codeVerifier) {
    missing.push("PKCE verifier");
  }

  if (missing.length === 0) {
    return "Missing OAuth callback parameters. Start sign-in again.";
  }

  const hostHint =
    window.location.hostname === "127.0.0.1"
      ? " You started sign-in on localhost but returned on 127.0.0.1 (or vice versa). Use one host consistently."
      : "";

  if (missing.includes("PKCE verifier") && input.code && input.loginIntentId) {
    return `OAuth callback lost the PKCE verifier (browser session was cleared or the host changed).${hostHint} Start sign-in again from the same URL you used initially.`;
  }

  return `Missing OAuth callback parameters (${missing.join(", ")}).${hostHint} Start sign-in again.`;
}