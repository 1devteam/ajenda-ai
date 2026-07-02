import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomerSession } from "../types";
import {
  buildSignInPath,
  canRefreshSession,
  clearSignInNotice,
  defaultSignInNotice,
  forceSignOut,
  isAccessTokenExpired,
  isAuthenticationFailure,
  isRefreshTokenExpired,
  readSignInNotice,
  resetForcedSignOutGuard,
  SESSION_EXPIRED_CLIENT_CODE,
  SESSION_FORCED_SIGNOUT_EVENT,
  shouldRefreshAccessToken,
} from "./sessionLifecycle";
import { SESSION_STORAGE_KEY } from "./session";

const NOW = Date.parse("2026-07-01T12:00:00.000Z");

function oidcSession(overrides: Partial<CustomerSession> = {}): CustomerSession {
  return {
    authMode: "oidc",
    tenantId: "tenant-1",
    phase: "operational",
    accessToken: "access-token",
    refreshToken: "refresh-token",
    expiresAt: new Date(NOW + 3_600_000).toISOString(),
    refreshExpiresAt: new Date(NOW + 86_400_000).toISOString(),
    email: "user@example.com",
    ...overrides,
  };
}

describe("session expiry helpers", () => {
  it("treats missing access expiry as expired", () => {
    expect(isAccessTokenExpired(oidcSession({ expiresAt: undefined }), NOW)).toBe(true);
  });

  it("detects expired access tokens", () => {
    expect(
      isAccessTokenExpired(oidcSession({ expiresAt: new Date(NOW - 1_000).toISOString() }), NOW),
    ).toBe(true);
  });

  it("keeps valid access tokens active", () => {
    expect(isAccessTokenExpired(oidcSession(), NOW)).toBe(false);
  });

  it("detects expired refresh tokens", () => {
    expect(
      isRefreshTokenExpired(oidcSession({ refreshExpiresAt: new Date(NOW - 1_000).toISOString() }), NOW),
    ).toBe(true);
  });

  it("allows refresh when refresh token is still valid", () => {
    expect(canRefreshSession(oidcSession(), NOW)).toBe(true);
  });

  it("refuses refresh when refresh token is missing", () => {
    expect(canRefreshSession(oidcSession({ refreshToken: undefined }), NOW)).toBe(false);
  });

  it("refreshes inside the one-minute buffer", () => {
    expect(
      shouldRefreshAccessToken(
        oidcSession({ expiresAt: new Date(NOW + 30_000).toISOString() }),
        NOW,
      ),
    ).toBe(true);
  });

  it("does not refresh when access token has plenty of time left", () => {
    expect(shouldRefreshAccessToken(oidcSession(), NOW)).toBe(false);
  });

  it("refreshes immediately when access token is already expired", () => {
    expect(
      shouldRefreshAccessToken(
        oidcSession({ expiresAt: new Date(NOW - 1_000).toISOString() }),
        NOW,
      ),
    ).toBe(true);
  });

  it("ignores api-key sessions for refresh decisions", () => {
    const apiKeySession: CustomerSession = {
      authMode: "api_key",
      tenantId: "tenant-1",
      phase: "operational",
      apiKey: "kid.secret",
      keyId: "kid",
    };
    expect(shouldRefreshAccessToken(apiKeySession, NOW)).toBe(false);
    expect(isAccessTokenExpired(apiKeySession, NOW)).toBe(false);
  });
});

describe("authentication failure detection", () => {
  it.each([
    "invalid bearer token",
    "invalid session token",
    "missing bearer token",
    "invalid or revoked api key",
    "refresh token is invalid or expired",
    "session has been revoked or expired",
    "missing authentication credentials",
  ])("flags %s as an auth failure", (detail) => {
    expect(isAuthenticationFailure({ status: 401, body: { detail } })).toBe(true);
  });

  it("flags structured authentication codes", () => {
    expect(
      isAuthenticationFailure({
        status: 401,
        body: { detail: { code: "AUTHENTICATION_REQUIRED", message: "missing authentication credentials" } },
      }),
    ).toBe(true);
    expect(
      isAuthenticationFailure({
        status: 401,
        body: { detail: { code: "INVALID_BEARER_TOKEN", message: "invalid bearer token" } },
      }),
    ).toBe(true);
  });

  it("flags client session-expired failures", () => {
    expect(
      isAuthenticationFailure({
        status: 401,
        body: { detail: "expired", code: SESSION_EXPIRED_CLIENT_CODE },
      }),
    ).toBe(true);
  });

  it("ignores non-auth 401 responses", () => {
    expect(isAuthenticationFailure({ status: 401, body: { detail: "membership inactive" } })).toBe(false);
  });

  it("ignores non-401 responses", () => {
    expect(isAuthenticationFailure({ status: 403, body: { detail: "invalid bearer token" } })).toBe(false);
  });
});

describe("forced sign-out flow", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    resetForcedSignOutGuard();
  });

  it("stores a sign-in notice and clears the customer session", () => {
    window.sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        authMode: "oidc",
        tenantId: "tenant-1",
        accessToken: "token",
        phase: "operational",
      }),
    );

    const handler = vi.fn();
    window.addEventListener(SESSION_FORCED_SIGNOUT_EVENT, handler);

    forceSignOut({
      reason: "refresh_expired",
      message: "Your sign-in session expired. Sign in again to continue.",
      returnPath: "/missions",
    });

    expect(window.sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(readSignInNotice()).toEqual({
      reason: "refresh_expired",
      message: "Your sign-in session expired. Sign in again to continue.",
      returnPath: "/missions",
    });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(buildSignInPath(readSignInNotice()!)).toBe("/signin?reason=refresh_expired&return=%2Fmissions");
  });

  it("deduplicates repeated forced sign-out calls", () => {
    const handler = vi.fn();
    window.addEventListener(SESSION_FORCED_SIGNOUT_EVENT, handler);

    forceSignOut({ reason: "auth_rejected" });
    forceSignOut({ reason: "auth_rejected" });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("provides default sign-in copy per reason", () => {
    expect(defaultSignInNotice("refresh_expired")).toContain("expired");
    expect(defaultSignInNotice("signed_out")).toContain("signed out");
  });

  it("clears stored sign-in notices", () => {
    forceSignOut({ reason: "access_expired" });
    clearSignInNotice();
    expect(readSignInNotice()).toBeNull();
  });
});