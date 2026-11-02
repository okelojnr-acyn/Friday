import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { TopBar } from "../ui/TopBar";

export function RequireAuth() {
  const { session, ready } = useAuth();
  if (!ready) return <div className="page spinner">Loading...</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <Layout />;
}

function Layout() {
  const { session, logout } = useAuth();
  if (!session) return null;
  return (
    <div>
      <TopBar email={session.email} role={session.role} onLogout={logout} />
      <Outlet />
    </div>
  );
}
