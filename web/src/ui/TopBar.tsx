import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { Button } from "./Button";

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
          <Button variant="ghost" size="sm">
            <Icon name="apps" size={16} />
            Apps
          </Button>
        </Link>
        <span className="field-label" title={role}>
          <Icon name="user" size={14} /> {email}
        </span>
        <Button variant="ghost" size="sm" onClick={onLogout} title="Log out">
          <Icon name="logout" size={16} />
        </Button>
      </div>
    </header>
  );
}
