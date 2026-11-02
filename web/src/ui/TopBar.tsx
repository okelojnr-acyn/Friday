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
        <Link to="/apps" title="Apps catalog">
          <Button variant="secondary" size="sm" className="btn-pill">
            <Icon name="apps" size={16} />
            Apps
          </Button>
        </Link>
        <span className="topbar-user" title={role}>
          <Avatar label={initials(email)} title={email} size={26} />
          {email}
        </span>
        <Button variant="ghost" size="sm" onClick={onLogout} title="Log out">
          <Icon name="logout" size={16} />
        </Button>
      </div>
    </header>
  );
}
