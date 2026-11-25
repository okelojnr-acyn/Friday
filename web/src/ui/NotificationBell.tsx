import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Icon } from "./Icon";

interface Notice {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
}

function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The notification inbox (kernel /me/notifications), the same in Friday
 * and in Minions: a bell with the unread count, a list that opens on tap,
 * each notice leading to where it's about. Checked on each page change,
 * when the app comes back to the front, and every minute. Hidden on a
 * kernel without the inbox. */
export function NotificationBell() {
  const [items, setItems] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);
  const [available, setAvailable] = useState(true);
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api
      .get<{ unread: number; items: Notice[] }>("/me/notifications")
      .then((r) => {
        setItems(r.items);
        setUnread(r.unread);
        setAvailable(true);
      })
      .catch(() => setAvailable(false));
  }, []);

  useEffect(load, [load, pathname]);
  useEffect(() => {
    const onShow = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onShow);
    const t = window.setInterval(load, 60_000);
    return () => {
      document.removeEventListener("visibilitychange", onShow);
      window.clearInterval(t);
    };
  }, [load]);

  // Close on a tap outside or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function markRead(body: { ids?: number[]; all?: boolean }) {
    try {
      await api.post("/me/notifications/read", body);
    } catch {
      // the next check shows the truth
    }
    load();
  }

  function go(n: Notice) {
    setOpen(false);
    if (!n.read_at) void markRead({ ids: [n.id] });
    if (!n.link) return;
    // Minions runs under /minions; Friday at the root. Within the same app
    // move in place, across apps load the other one.
    const inMinions = window.location.pathname.startsWith("/minions");
    const toMinions = n.link.startsWith("/minions");
    if (inMinions && toMinions) navigate(n.link.slice("/minions".length) || "/");
    else if (!inMinions && !toMinions) navigate(n.link);
    else window.location.href = n.link;
  }

  if (!available) return null;
  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="bell-button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="bell" size={20} />
        {unread > 0 ? <span className="bell-count">{unread > 9 ? "9+" : unread}</span> : null}
      </button>
      {open ? (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="bell-head">
            <strong>Notifications</strong>
            {unread > 0 ? (
              <button type="button" className="bell-link" onClick={() => markRead({ all: true })}>
                Mark all read
              </button>
            ) : null}
          </div>
          {items.length === 0 ? (
            <p className="bell-empty">Nothing yet. Tasks given to you, claims waiting for you, and decisions on yours show up here.</p>
          ) : (
            <ul className="bell-list">
              {items.map((n) => (
                <li key={n.id}>
                  <button type="button" className={`bell-item${n.read_at ? "" : " unread"}`} onClick={() => go(n)}>
                    <span className="bell-title">{n.title}</span>
                    {n.body ? <span className="bell-body">{n.body}</span> : null}
                    <span className="bell-time">{ago(n.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
