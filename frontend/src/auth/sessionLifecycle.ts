import type { ApiFailure, CustomerSession } from "../types";
import { clearSession, loadSession, SESSION_CHANGED_EVENT } from "./session";

export const SIGN_IN_NOTICE_STORAGE_KEY = "ajenda.signin.notice.v1";
export const SESSION_FORCED_SIGNOUT_EVENT = "ajenda:session-forced-signout";
export const SESSION_EXPIRED_CLIENT_CODE = "SESSION_EXPIRED";

export type SessionSignOutReason =
  | "access_expired"
  | "refresh_expired"
  | "refresh_failed"
  | "auth_rejected"
  | "signed_out";

export interface SignInNotice {
  reason: SessionSignOutReason;
  message: string;
  returnPath?: string;
}

const AUTH_FAILURE_DETAILS = new Set([
  "invalid bearer token",
  "invalid session token",
  "missing bearer token",
  "invalid or revoked api key",
  "refresh token is invalid or expired",
  "session has been revoked or expired",
  "missing authentication credentials",
]);

const AUTH_FAILURE_CODES = new Set([
  "AUTHENTICATION_REQUIRED",
  "INVALID_BEARER_TOKEN",
  SESSION_EXPIRED_CLIENT_CODE,
]);

let forcedSignOutInFlight = false;

export function resetForcedSignOutGuard(): void {
  forcedSignOutInFlight = false;
}

function parseInstant(value: string | undefined): number | null {
  if (!value?.trim()) {
    return null;
  }
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function isAccessTokenExpired(
  session: CustomerSession,
  nowMs: number = Date.now(),
): boolean {
  if (session.authMode !== "oidc") {
    return false;
  }
  const expiresMs = parseInstant(session.expiresAt);
  if (expiresMs === null) {
    return true;
  }
  return nowMs >= expiresMs;
}

export function isRefreshTokenExpired(
  session: CustomerSession,
  nowMs: number = Date.now(),
): boolean {
  if (session.authMode !== "oidc") {
    return false;
  }
  if (!session.refreshToken?.trim()) {
    return true;
  }
  const refreshExpiresMs = parseInstant(session.refreshExpiresAt);
  if (refreshExpiresMs === null) {
    return false;
  }
  return nowMs >= refreshExpiresMs;
}

export function canRefreshSession(session: CustomerSession, nowMs: number = Date.now()): boolean {
  return (
    session.authMode === "oidc" &&
    Boolean(session.refreshToken?.trim()) &&
    !isRefreshTokenExpired(session, nowMs)
  );
}

export function shouldRefreshAccessToken(session: CustomerSession, nowMs: number = Date.now()): boolean {
  if (session.authMode !== "oidc" || !session.refreshToken?.trim()) {
    return false;
  }
  if (isRefreshTokenExpired(session, nowMs)) {
    return false;
  }
  if (isAccessTokenExpired(session, nowMs)) {
    return true;
  }
  const expiresMs = parseInstant(session.expiresAt);
  if (expiresMs === null) {
    return true;
  }
  return nowMs >= expiresMs - 60_000;
}

export function extractAuthFailureDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return null;
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    const message = (detail as { message: unknown }).message;
    return typeof message === "string" ? message : null;
  }
  return null;
}

export function extractErrorCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  if ("code" in body && typeof (body as { code: unknown }).code === "string") {
    return (body as { code: string }).code;
  }
  if ("detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "object" && detail !== null && "code" in detail) {
      const code = (detail as { code: unknown }).code;
      return typeof code === "string" ? code : null;
    }
  }
  return null;
}

export function isAuthenticationFailure(error: unknown): boolean {
  const failure = error as Partial<ApiFailure>;
  if (failure.status !== 401) {
    return false;
  }
  const code = extractErrorCode(failure.body);
  if (code && AUTH_FAILURE_CODES.has(code)) {
    return true;
  }
  const detail = extractAuthFailureDetail(failure.body);
  if (!detail) {
    return false;
  }
  return AUTH_FAILURE_DETAILS.has(detail);
}

export function sessionExpiredFailure(message: string, reason: SessionSignOutReason = "auth_rejected"): ApiFailure {
  return {
    status: 401,
    message: "Session expired",
    body: {
      detail: message,
      code: SESSION_EXPIRED_CLIENT_CODE,
      reason,
    },
  };
}

export function defaultSignInNotice(reason: SessionSignOutReason): string {
  switch (reason) {
    case "access_expired":
    case "refresh_expired":
    case "refresh_failed":
    case "auth_rejected":
      return "Your sign-in session expired. Sign in again to continue.";
    case "signed_out":
      return "You have been signed out.";
    default:
      return "Sign in to continue.";
  }
}

export function saveSignInNotice(notice: SignInNotice): void {
  window.sessionStorage.setItem(SIGN_IN_NOTICE_STORAGE_KEY, JSON.stringify(notice));
}

export function readSignInNotice(): SignInNotice | null {
  const raw = window.sessionStorage.getItem(SIGN_IN_NOTICE_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<SignInNotice>;
    if (typeof parsed.message !== "string" || !parsed.message.trim()) {
      return null;
    }
    const reason = parsed.reason ?? "auth_rejected";
    return {
      reason,
      message: parsed.message,
      returnPath: typeof parsed.returnPath === "string" ? parsed.returnPath : undefined,
    };
  } catch {
    return null;
  }
}

export function clearSignInNotice(): void {
  window.sessionStorage.removeItem(SIGN_IN_NOTICE_STORAGE_KEY);
}

export function buildSignInPath(notice?: SignInNotice): string {
  const params = new URLSearchParams();
  if (notice?.reason) {
    params.set("reason", notice.reason);
  }
  if (notice?.returnPath?.trim()) {
    params.set("return", notice.returnPath.trim());
  }
  const query = params.toString();
  return query ? `/signin?${query}` : "/signin";
}

export function forceSignOut(options: {
  reason: SessionSignOutReason;
  message?: string;
  returnPath?: string;
}): void {
  if (forcedSignOutInFlight) {
    return;
  }
  forcedSignOutInFlight = true;

  const message = options.message?.trim() || defaultSignInNotice(options.reason);
  const returnPath = options.returnPath ?? `${window.location.pathname}${window.location.search}`;
  const notice: SignInNotice = {
    reason: options.reason,
    message,
    returnPath,
  };

  saveSignInNotice(notice);
  clearSession();
  window.dispatchEvent(new CustomEvent(SESSION_FORCED_SIGNOUT_EVENT, { detail: notice }));
  window.dispatchEvent(new Event(SESSION_CHANGED_EVENT));
}

export function hasActiveCustomerSession(): boolean {
  return loadSession() !== null;
}