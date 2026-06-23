import { Navigate, Outlet } from "react-router-dom";
import { isOperational, loadSession } from "../auth/session";

interface ProtectedRouteProps {
  requireOperational?: boolean;
}

export default function ProtectedRoute({ requireOperational = false }: ProtectedRouteProps) {
  const session = loadSession();

  if (!session) {
    return <Navigate to="/signin" replace />;
  }

  if (requireOperational && !isOperational(session)) {
    return <Navigate to="/promote" replace />;
  }

  return <Outlet />;
}