import { useDemoRoles } from "../lib/demo";
import { SIGNUP_URL } from "../ui/GussWidget";
import { useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { GussWidget } from "../ui/GussWidget";
import { NewVersionBanner } from "../ui/NewVersionBanner";
import { TopBar } from "../ui/TopBar";
import { PageErrorBoundary } from "../ui/PageErrorBoundary";

const STAFF_ROLES = ["member", "team_leader"];

export function RequireAuth() {
  const { session, ready } = useAuth();
  // Staff (and team leaders) work only in Minions (owner, 2026-11-25:
  // "nothing exposing Friday to minions at all"), whatever their jobs.
  // The server limits what any token can read or change; this keeps
  // Friday's owner and manager screens from ever rendering for them.
  const staff = !!session && STAFF_ROLES.includes(session.role);
  useEffect(() => {
    if (staff) window.location.replace("/minions/");
  }, [staff]);

  if (!ready) return <div className="page spinner">Loading...</div>;
  if (!session) return <Navigate to="/login" replace />;
  if (staff) return <div className="page spinner">Opening your staff app…</div>;
  return <Layout />;
}

function Layout() {
  const { session, logout } = useAuth();
  if (!session) return null;
  return (
    <div>
      <DemoBanner />
      <TopBar email={session.email} role={session.role} onLogout={logout} />
      <PageErrorBoundary>
        <Outlet />
      </PageErrorBoundary>
      <GussWidget />
      <NewVersionBanner />
    </div>
  );
}

/** On the demo Friday: say so, once, at the top. */
function DemoBanner() {
  const demo = useDemoRoles();
  return demo ? (
    <div role="note" className="demo-banner">
      Demo: a sample shop. Try anything; everything goes back to the start every night.{" "}
      <a href={SIGNUP_URL} target="_blank" rel="noopener" style={{ color: "inherit", fontWeight: 600 }}>
        Create your account
      </a>
    </div>
  ) : null;
}
