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
        <a href="https://fridayhost.dev/app" title="Friday Host dashboard" aria-label="Friday Host dashboard">
          <Button variant="secondary" size="sm" className="btn-pill">
            <Icon name="arrow-up-right" size={16} />
            <span className="topbar-label">Friday Host</span>
          </Button>
        </a>
        <Link to="/apps" title="Apps catalog" aria-label="Apps catalog">
          <Button variant="secondary" size="sm" className="btn-pill">
            <Icon name="apps" size={16} />
            <span className="topbar-label">Apps</span>
          </Button>
        </Link>
        <Link to="/settings/members" title="Members" aria-label="Members">
          <Button variant="secondary" size="sm" className="btn-pill">
            <Icon name="users" size={16} />
            <span className="topbar-label">Members</span>
          </Button>
        </Link>
        <Link to="/settings/integrations" title="Integrations" aria-label="Integrations">
          <Button variant="secondary" size="sm" className="btn-pill">
            <Icon name="link-2" size={16} />
            <span className="topbar-label">Integrations</span>
          </Button>
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
