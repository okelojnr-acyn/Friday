import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";
import { Link, Outlet, useLocation } from "react-router-dom";
import { PageErrorBoundary } from "../ui/PageErrorBoundary";
import { APP_ICONS } from "../ui/AppTile";
import { Icon } from "../ui/Icon";
import { navForPath, type NavItem } from "./appNav";

const ActiveNav = createContext<NavItem | null>(null);

/** The rail entry for this page: its name (so "Pay details" isn't titled
 * "Employees") and its hint. */
export const useActiveNav = () => useContext(ActiveNav);

/** The page's one small hint, under its title (plan 18: hints above the
 * title read as stray text). */
export function AppHint() {
  const hint = useActiveNav()?.hint;
  return hint ? <p className="app-hint">{hint}</p> : null;
}

/** Every app in the Apps & integrations layout (owner's foundation
 * design): a left rail with the app's sections, the page beside it. On a
 * phone the rail becomes one scrolling row (same CSS as /apps). */
export function AppFrame() {
  const { pathname, search } = useLocation();
  const nav = navForPath(pathname);
  if (!nav)
    return (
      <PageErrorBoundary>
        <Outlet />
      </PageErrorBoundary>
    );

  const isActive = (item: NavItem) => {
    const [path, query] = item.to.split("?");
    return pathname === path && (query ? search.includes(query) : !search.includes("tab="));
  };
  const all = nav.sections.flatMap(([, items]) => items);
  const active = all.find(isActive) ?? all.find((i) => !i.external && pathname.startsWith(i.to.split("?")[0] + "/"));
  const tile = APP_ICONS[nav.app];

  return (
    <div className="page app-frame">
      <div className="hub">
        <nav className="hub-nav" aria-label={nav.label}>
          <Link to={nav.sections[0][1][0].to} className="app-frame-title">
            <span className="app-tile-icon app-tile-icon-sm" style={{ ["--tile" as string]: tile?.color }}>
              <Icon name={tile?.icon ?? "app-window"} size={18} />
            </span>
            <span>{nav.label}</span>
          </Link>
          {nav.sections.map(([title, items]) => (
            <div key={title} className="app-frame-section">
              <div className="app-frame-section-title">{title}</div>
              {items.map((item) =>
                item.external ? (
                  <a key={item.to} href={item.to} className="hub-nav-item">
                    <Icon name={item.icon} size={16} />
                    <span>{item.label}</span>
                  </a>
                ) : (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={`hub-nav-item${item === active ? " active" : ""}`}
                    aria-current={item === active ? "page" : undefined}
                  >
                    <Icon name={item.icon} size={16} />
                    <span>{item.label}</span>
                    {item.waiting ? <WaitingCount {...item.waiting} /> : null}
                  </Link>
                ),
              )}
            </div>
          ))}
        </nav>
        <div className="hub-main">
          <ActiveNav.Provider value={active ?? null}>
            <PageErrorBoundary>
              <Outlet />
            </PageErrorBoundary>
          </ActiveNav.Provider>
        </div>
      </div>
    </div>
  );
}

/** How many in a queue are waiting for someone, beside its rail entry.
 * Nothing when none are, or when this person can't read the list.
 * shortcut: counts the first page the list returns; give the APIs a count
 * endpoint if a queue ever holds more than a page. */
function WaitingCount({ path, statuses }: { path: string; statuses: string[] }) {
  const [n, setN] = useState(0);
  const { pathname } = useLocation();
  useEffect(() => {
    let live = true;
    api
      .get<{ status?: string }[]>(path)
      .then((rows) => live && setN(Array.isArray(rows) ? rows.filter((r) => statuses.includes(String(r.status))).length : 0))
      .catch(() => live && setN(0));
    return () => {
      live = false;
    };
    // Recount when the person moves between pages (they may have just dealt with one).
  }, [path, statuses, pathname]);
  return n > 0 ? (
    <span className="hub-nav-count" aria-label={`${n} waiting`}>
      {n}
    </span>
  ) : null;
}
