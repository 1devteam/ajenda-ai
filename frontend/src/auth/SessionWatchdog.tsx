import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router";
import { ensureFreshSession } from "../api/client";
import { useAuth } from "./AuthProvider";
import {
  buildSignInPath,
  canRefreshSession,
  forceSignOut,
  isAccessTokenExpired,
  isRefreshTokenExpired,
  resetForcedSignOutGuard,
  SESSION_FORCED_SIGNOUT_EVENT,
  shouldRefreshAccessToken,
  type SignInNotice,
} from "./sessionLifecycle";

const WATCHDOG_INTERVAL_MS = 30_000;
const PUBLIC_PATH_PREFIXES = ["/signin", "/signup", "/verify-email", "/auth/callback"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export default function SessionWatchdog() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const locationRef = useRef(location.pathname + location.search);

  useEffect(() => {
    locationRef.current = `${location.pathname}${location.search}`;
  }, [location.pathname, location.search]);

  useEffect(() => {
    function redirectToSignIn(notice?: SignInNotice) {
      const target = buildSignInPath(notice);
      if (`${location.pathname}${location.search}` === target) {
        return;
      }
      navigate(target, { replace: true });
    }

    function handleForcedSignOut(event: Event) {
      const notice = (event as CustomEvent<SignInNotice>).detail;
      redirectToSignIn(notice);
    }

    window.addEventListener(SESSION_FORCED_SIGNOUT_EVENT, handleForcedSignOut);
    return () => {
      window.removeEventListener(SESSION_FORCED_SIGNOUT_EVENT, handleForcedSignOut);
    };
  }, [location.pathname, location.search, navigate]);

  useEffect(() => {
    if (!session || session.authMode !== "oidc") {
      resetForcedSignOutGuard();
      return;
    }

    if (isPublicPath(location.pathname)) {
      return;
    }

    let cancelled = false;

    async function maintainSession() {
      if (cancelled || !session || session.authMode !== "oidc") {
        return;
      }

      if (isRefreshTokenExpired(session)) {
        forceSignOut({
          reason: "refresh_expired",
          message: "Your sign-in session expired. Sign in again to continue.",
          returnPath: locationRef.current,
        });
        return;
      }

      if (!canRefreshSession(session)) {
        return;
      }

      if (!shouldRefreshAccessToken(session) && !isAccessTokenExpired(session)) {
        return;
      }

      try {
        await ensureFreshSession(session);
      } catch {
        // ensureFreshSession signs out and redirects on hard auth failure.
      }
    }

    void maintainSession();
    const timer = window.setInterval(() => {
      void maintainSession();
    }, WATCHDOG_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [location.pathname, session]);

  return null;
}