import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { Button } from "./Button";
import { Avatar } from "./Avatar";
import { initials } from "./resource/fieldFormat";

interface TopBarProps {
  email: string;
  role: string;
  onLogout: () => void;
}

export function TopBar({ email, role, onLogout }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link to="/" className="topbar-brand">
          Friday
        </Link>
      </div>
      <div className="topbar-right">
        <a href="https://fridayhost.dev/app" title="Friday Host dashboard" aria-label="Friday Host dashboard" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="arrow-up-right" size={16} />
            <span className="topbar-label">Friday Host</span>
        </a>
        <Link to="/apps" title="Apps catalog" aria-label="Apps catalog" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="apps" size={16} />
            <span className="topbar-label">Apps</span>
        </Link>
        <Link to="/settings/members" title="Admins and managers" aria-label="Admins" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="users" size={16} />
            <span className="topbar-label">Admins</span>
        </Link>
        <Link to="/settings/business" title="Business settings" aria-label="Business settings" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="calculator" size={16} />
            <span className="topbar-label">Business</span>
        </Link>
        {role === "owner" || role === "admin" ? (
          <Link to="/settings/import" title="Import data" aria-label="Import data" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="upload" size={16} />
            <span className="topbar-label">Import</span>
          </Link>
        ) : null}
        <Link to="/settings/integrations" title="Integrations" aria-label="Integrations" className="btn btn-secondary btn-sm btn-pill">
            <Icon name="link-2" size={16} />
            <span className="topbar-label">Integrations</span>
        </Link>
        <span className="topbar-user" title={role}>
          <Avatar label={initials(email)} title={email} size={26} />
          <span className="topbar-email">{email}</span>
        </span>
        <Button variant="ghost" size="sm" onClick={onLogout} title="Log out" aria-label="Log out">
          <Icon name="logout" size={16} />
        </Button>
      </div>
    </header>
  );
}
