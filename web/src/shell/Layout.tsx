import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { fetchMyPermissions } from "../lib/permissions";
import { GussWidget } from "../ui/GussWidget";
import { NewVersionBanner } from "../ui/NewVersionBanner";
import { TopBar } from "../ui/TopBar";

const STAFF_ROLES = ["member", "team_leader"];
// Jobs that work in Friday's back office even for staff (plan 12.1).
const DESK_PERMS = ["accounting", "hr", "purchasing"];

export function RequireAuth() {
  const { session, ready } = useAuth();
  // Staff work from the Minions app (plan 12.6); Friday's admin screens
  // are unusable for a cashier on a phone. undefined = still checking.
  const [toMinions, setToMinions] = useState<boolean | undefined>(undefined);
  const staff = !!session && STAFF_ROLES.includes(session.role);
  useEffect(() => {
    if (!staff) return;
    fetchMyPermissions()
      .then((me) => setToMinions(!me.perms.some((p) => DESK_PERMS.includes(p))))
      .catch(() => setToMinions(true));
  }, [staff]);
  useEffect(() => {
    if (toMinions) window.location.replace("/minions/");
  }, [toMinions]);

  if (!ready) return <div className="page spinner">Loading...</div>;
  if (!session) return <Navigate to="/login" replace />;
  if (staff && toMinions !== false) return <div className="page spinner">Opening your staff app…</div>;
  return <Layout />;
}

function Layout() {
  const { session, logout } = useAuth();
  if (!session) return null;
  return (
    <div>
      <TopBar email={session.email} role={session.role} onLogout={logout} />
      <Outlet />
      <GussWidget />
      <NewVersionBanner />
    </div>
  );
}
