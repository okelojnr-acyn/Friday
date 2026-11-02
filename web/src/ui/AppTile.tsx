import { Link } from "react-router-dom";
import { Icon } from "./Icon";

interface AppTileProps {
  to: string;
  icon: string;
  label: string;
  description?: string;
}

const KNOWN_ICONS = new Set(["target", "receipt", "kanban", "box"]);

// A distinct accent per app -- the closest Friday gets to Odoo's
// bespoke, colorful per-app icon without a full illustration pipeline:
// one line-icon set, tinted differently per app so the grid still reads
// as "many distinct apps," not one repeated glyph.
const ICON_COLOR: Record<string, string> = {
  target: "#d6483f",
  receipt: "#2f9e63",
  kanban: "#3f6fd6",
  box: "#b5792a",
  "app-window": "var(--accent)",
};

export function AppTile({ to, icon, label }: AppTileProps) {
  const iconName = (KNOWN_ICONS.has(icon) ? icon : "app-window") as
    | "target"
    | "receipt"
    | "kanban"
    | "box"
    | "app-window";
  return (
    <Link to={to} className="app-tile" title={label}>
      <span className="app-tile-icon" style={{ color: ICON_COLOR[iconName] }}>
        <Icon name={iconName} size={20} />
      </span>
      <span className="app-tile-label">{label}</span>
    </Link>
  );
}
