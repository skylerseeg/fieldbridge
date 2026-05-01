import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/lib/auth";

/**
 * Route gate. Wraps the authenticated part of the app.
 * If no token, bounces to /login and preserves the intended destination
 * in location.state so LoginPage can redirect back after sign-in.
 */
export function RequireAuth() {
  const token = useAuth((s) => s.token);
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <Outlet />;
}
