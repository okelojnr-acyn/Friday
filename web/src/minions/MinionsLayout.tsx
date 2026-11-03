import { Navigate, Outlet, Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Icon, type IconName } from "../ui/Icon";
import { Button } from "../ui/Button";
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

const NAV: { to: string; icon: IconName; label: string }[] = [
  { to: "/", icon: "kanban", label: "My Tasks" },
  { to: "/expense-claims", icon: "receipt", label: "Expense Claims" },
  { to: "/payroll", icon: "wallet", label: "Payroll" },
  { to: "/wallet", icon: "key", label: "Wallet" },
];

function MinionsLayout() {
  const { session, logout } = useAuth();
  if (!session) return null;
  return (
    <div>
      <header className="topbar">
        <div className="topbar-left">
          <Link to="/" className="topbar-brand">
            Friday Minions
          </Link>
        </div>
        <div className="topbar-right">
          {NAV.map((item) => (
            <Link key={item.to} to={item.to} title={item.label}>
              <Button variant="secondary" size="sm" className="btn-pill">
                <Icon name={item.icon} size={16} />
                {item.label}
              </Button>
            </Link>
          ))}
          <span className="topbar-user" title={session.role}>
            <Avatar label={initials(session.email)} title={session.email} size={26} />
            {session.email}
          </span>
          <Button variant="ghost" size="sm" onClick={logout} title="Log out">
            <Icon name="logout" size={16} />
          </Button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
