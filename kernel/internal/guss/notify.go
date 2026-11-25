package guss

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/inbox"
)

// quiet: 21:00-07:00 in the person's own time zone, when notices arrive
// without a sound (owner default, 2026-11-25). They are never held back.
func quiet(t time.Time, tz string) bool {
	loc, err := time.LoadLocation(tz)
	if err != nil || tz == "" {
		loc = time.UTC
	}
	h := t.In(loc).Hour()
	return h >= 21 || h < 7
}

// telegramText: the inbox message, with a link to where it leads for
// someone with that role.
func telegramText(m inbox.Message, role, webURL string) string {
	return m.Title + ": " + m.Body + "\n" + strings.TrimRight(webURL, "/") + m.Path(role)
}

// Notify sends an event's message (the same one the inbox files) to the
// people it names who have linked Telegram, through the business's Guss
// (POST /api/notify). The kernel's event queue calls it and retries on an
// error. Nobody linked, Guss not connected, or a Guss without /api/notify:
// nothing to send, not an error.
func (h *Handlers) Notify(ctx context.Context, orgID, typ string, payload []byte) error {
	var n inbox.Notice
	if err := json.Unmarshal(payload, &n); err != nil || len(n.ToUserIDs) == 0 {
		return nil
	}
	m, ok := inbox.Compose(typ, n)
	if !ok {
		return nil
	}
	rows, err := h.Pool.Query(ctx,
		`SELECT l.telegram_id, COALESCE(NULLIF(u.time_zone, ''), o.time_zone), mb.role FROM core.guss_links l
		 JOIN core.users u ON u.id = l.user_id JOIN core.orgs o ON o.id = l.org_id
		 JOIN core.memberships mb ON mb.org_id = l.org_id AND mb.user_id = l.user_id
		 WHERE l.org_id::text = $1 AND l.user_id::text = ANY($2) ORDER BY l.telegram_id`,
		orgID, n.ToUserIDs)
	if err != nil {
		return err
	}
	type target struct {
		id       int64
		tz, role string // tz: theirs, else the business's ("" = UTC)
	}
	var targets []target
	for rows.Next() {
		var t target
		if rows.Scan(&t.id, &t.tz, &t.role) == nil {
			targets = append(targets, t)
		}
	}
	rows.Close()
	if len(targets) == 0 {
		return nil
	}
	c, err := h.load(ctx, orgID)
	if err != nil {
		return nil // Guss isn't connected here
	}
	// shortcut: a failure part-way retries everyone, so someone may get a
	// notice twice; track per person if that happens often.
	now := time.Now()
	for _, t := range targets {
		body := map[string]any{"telegram_id": t.id, "text": telegramText(m, t.role, h.WebURL), "silent": quiet(now, t.tz)}
		status, err := h.callJSON(ctx, c, http.MethodPost, "/api/notify", body, nil)
		if err != nil {
			if strings.Contains(err.Error(), "404") || strings.Contains(err.Error(), "no Telegram bot") {
				log.Printf("guss notice for org %s skipped: %v", orgID, err)
				return nil // an older Guss, or one without a bot: retrying won't help
			}
			if status == http.StatusBadRequest {
				return nil
			}
			return err
		}
	}
	return nil
}
