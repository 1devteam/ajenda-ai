import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { isOperational } from "../auth/session";

interface ProtectedRouteProps {
  requireOperational?: boolean;
}

export default function ProtectedRoute({ requireOperational = false }: ProtectedRouteProps) {
  const { session } = useAuth();

  if (!session) {
    return <Navigate to="/signin" replace />;
  }

  if (requireOperational && !isOperational(session)) {
    return <Navigate to="/promote" replace />;
  }

  return <Outlet />;
}