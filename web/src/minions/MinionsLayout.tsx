import { Link, Navigate, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useMyPermissions, type MyPermissions } from "../lib/permissions";
import { Icon, type IconName } from "../ui/Icon";
import { Avatar } from "../ui/Avatar";
import { initials } from "../ui/resource/fieldFormat";

/** Minions' own trimmed shell -- reuses useAuth/Icon/Button/Avatar
 * unchanged, but doesn't reuse ui/TopBar: that component's nav links
 * (Apps/Members/Integrations) are admin-shell concerns Minions
 * deliberately doesn't surface. This is the one real tradeoff of
 * shipping Minions as a second entry in the same package rather than a
 * fully separate project -- admin-only code is kept out by routing, not
 * physical separation, so this layout (and the route tree in
 * MinionsApp.tsx) is what actually enforces the employee-facing scope. */
export function RequireMinionsAuth() {
  const { session, ready } = useAuth();
  if (!ready) return <div className="page spinner">Loading...</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <MinionsLayout />;
}

/** The staff app's tabs (plan 12.6/12.7): a bottom bar, as phone apps
 * have it, showing only what this person can use. */
function tabsFor(me: MyPermissions | null): { to: string; icon: IconName; label: string }[] {
  const tabs: { to: string; icon: IconName; label: string }[] = [
    { to: "/", icon: "kanban", label: "Today" },
    { to: "/expense-claims", icon: "receipt", label: "Claims" },
    { to: "/payroll", icon: "wallet", label: "Pay" },
  ];
  if (me?.rules["claims.approve"]) tabs.push({ to: "/team", icon: "users", label: "Team" });
  tabs.push({ to: "/me", icon: "user", label: "Me" });
  return tabs;
}

function MinionsLayout() {
  const { session } = useAuth();
  const me = useMyPermissions();
  if (!session) return null;
  return (
    <div className="minions-shell">
      <header className="minions-top">
        <Link to="/" className="topbar-brand">
          Friday Minions
        </Link>
        <Link to="/me" className="minions-avatar" aria-label="Me">
          <Avatar label={initials(session.email)} title={session.email} size={30} />
        </Link>
      </header>
      <main className="minions-main">
        <Outlet />
      </main>
      <nav className="minions-tabs" aria-label="Minions">
        {tabsFor(me).map((t) => (
          <NavLink key={t.to} to={t.to} end={t.to === "/"} className={({ isActive }) => `minions-tab${isActive ? " active" : ""}`}>
            <Icon name={t.icon} size={22} />
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
