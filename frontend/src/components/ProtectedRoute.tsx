import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { isOperational } from "../auth/session";
import {
  buildSignInPath,
  canRefreshSession,
  forceSignOut,
  isAccessTokenExpired,
  isRefreshTokenExpired,
} from "../auth/sessionLifecycle";

interface ProtectedRouteProps {
  requireOperational?: boolean;
}

export default function ProtectedRoute({ requireOperational = false }: ProtectedRouteProps) {
  const { session } = useAuth();
  const location = useLocation();

  if (!session) {
    return (
      <Navigate
        to={buildSignInPath({
          reason: "signed_out",
          message: "Sign in to continue.",
          returnPath: `${location.pathname}${location.search}`,
        })}
        replace
      />
    );
  }

  if (session.authMode === "oidc") {
    if (isRefreshTokenExpired(session) || (isAccessTokenExpired(session) && !canRefreshSession(session))) {
      forceSignOut({
        reason: isRefreshTokenExpired(session) ? "refresh_expired" : "access_expired",
        message: "Your sign-in session expired. Sign in again to continue.",
        returnPath: `${location.pathname}${location.search}`,
      });
      return (
        <Navigate
          to={buildSignInPath({
            reason: "access_expired",
            message: "Your sign-in session expired. Sign in again to continue.",
            returnPath: `${location.pathname}${location.search}`,
          })}
          replace
        />
      );
    }
  }

  if (requireOperational && !isOperational(session)) {
    return <Navigate to="/promote" replace />;
  }

  return <Outlet />;
}