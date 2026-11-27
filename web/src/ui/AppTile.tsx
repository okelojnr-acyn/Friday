import { Link } from "react-router-dom";
import { AppMark, hasAppMark } from "./AppMark";
import { Icon, type IconName } from "./Icon";

interface AppTileProps {
  to: string;
  // The app's registry name ("crm", "pos", ...); picks the icon and tint.
  app: string;
  label: string;
  description?: string;
  // True for a separate HTML entry (e.g. pos.html) rather than a route
  // within this SPA -- React Router's Link can't navigate across
  // document/bundle boundaries, so this needs a real browser navigation
  // instead of a client-side route change.
  external?: boolean;
}

// One silhouette and one tint per app, chosen here by app name rather
// than the kernel catalog's icon field, so the grid never shows two apps
// with the same glyph (it used to: anything outside four names fell back
// to a generic window, and Point of Sale reused Invoicing's receipt).
// `label` overrides the catalog's name where the owner renamed an app.
export const APP_ICONS: Record<string, { icon: IconName; color: string; label?: string }> = {
  crm: { icon: "funnel", color: "#d6483f" },
  invoicing: { icon: "invoice", color: "#2f9e63" },
  projects: { icon: "kanban", color: "#3f6fd6" },
  inventory: { icon: "box", color: "#b5792a" },
  accounting: { icon: "calculator", color: "#6b5bd2" },
  web3: { icon: "chain", color: "#0f8f9c" },
  minions: { icon: "users", color: "#c2417a", label: "People" },
  fleets: { icon: "truck", color: "#4d6b2f" },
  pos: { icon: "till", color: "#e07a35" },
  store: { icon: "storefront", color: "#1f8a70" },
  more: { icon: "plus", color: "#7a7468" },
};

export function AppTile({ to, app, label, external }: AppTileProps) {
  const { icon, color } = APP_ICONS[app] ?? { icon: "app-window" as IconName, color: "var(--accent)" };
  const content = (
    <>
      <span className="app-tile-icon" style={{ ["--tile" as string]: color }}>
        {hasAppMark(app) ? <AppMark app={app} size={44} /> : <Icon name={icon} size={30} />}
      </span>
      <span className="app-tile-label">{label}</span>
    </>
  );
  if (external) {
    return (
      <a href={to} className="app-tile" title={label}>
        {content}
      </a>
    );
  }
  return (
    <Link to={to} className="app-tile" title={label}>
      {content}
    </Link>
  );
}
