import { Link } from "react-router-dom";
import { Icon } from "./Icon";

interface AppTileProps {
  to: string;
  icon: string;
  label: string;
  description: string;
}

const KNOWN_ICONS = new Set(["target", "receipt", "kanban", "box"]);

export function AppTile({ to, icon, label, description }: AppTileProps) {
  const iconName = (KNOWN_ICONS.has(icon) ? icon : "app-window") as
    | "target"
    | "receipt"
    | "kanban"
    | "box"
    | "app-window";
  return (
    <Link to={to} className="app-tile">
      <span className="app-tile-icon">
        <Icon name={iconName} size={20} />
      </span>
      <span className="app-tile-label">{label}</span>
      <span className="app-tile-desc">{description}</span>
    </Link>
  );
}
