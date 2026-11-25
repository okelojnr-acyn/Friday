package guss

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// notice is what Minions' HR events carry (HR plan phase 1).
type notice struct {
	ToUserIDs     []string `json:"to_user_ids"`
	FromName      string   `json:"from_name"`
	AmountCents   int64    `json:"amount_cents"`
	Currency      string   `json:"currency"`
	Description   string   `json:"description"`
	Status        string   `json:"status"`
	Note          string   `json:"note"`
	DecidedByName string   `json:"decided_by_name"`
	Method        string   `json:"method"`
}

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

// money: "KES 1,500" (cents shown only when there are some).
func money(cents int64, currency string) string {
	whole := strconv.FormatInt(cents/100, 10)
	var b strings.Builder
	for i, r := range whole {
		if i > 0 && (len(whole)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	if c := cents % 100; c != 0 {
		fmt.Fprintf(&b, ".%02d", c)
	}
	return strings.TrimSpace(strings.ToUpper(currency) + " " + b.String())
}

// noticeText is the message for one event, "" for none.
// shortcut: English only; follow Guss's business language when asked.
func noticeText(typ string, n notice, webURL string) string {
	amount, what := money(n.AmountCents, n.Currency), strings.TrimSpace(n.Description)
	minions := strings.TrimRight(webURL, "/") + "/minions/"
	switch typ {
	case "minions.approval.needed":
		return fmt.Sprintf("%s asks you to approve a claim: %s for %s.\nDecide in Minions, Team: %steam", n.FromName, amount, what, minions)
	case "minions.expense_claim.decided":
		if n.Status == "rejected" {
			return fmt.Sprintf("%s rejected your claim for %s (%s): %s\nFix it and send it again in Minions, Claims: %sexpense-claims",
				n.DecidedByName, what, amount, n.Note, minions)
		}
		return fmt.Sprintf("%s approved your claim for %s (%s).", n.DecidedByName, what, amount)
	case "minions.expense_claim.paid":
		how := map[string]string{"mpesa": " by M-Pesa", "bank": " by bank transfer", "cash": " in cash", "crypto": " to your wallet"}[n.Method]
		return fmt.Sprintf("Your claim for %s (%s) was paid%s.", what, amount, how)
	}
	return ""
}

// Notify delivers an HR event to the people it names who have linked
// Telegram, through the business's Guss (POST /api/notify). The kernel's
// event queue calls it and retries on an error. Nobody linked, Guss not
// connected, or a Guss without /api/notify: nothing to send, not an error.
func (h *Handlers) Notify(ctx context.Context, orgID, typ string, payload []byte) error {
	var n notice
	if err := json.Unmarshal(payload, &n); err != nil || len(n.ToUserIDs) == 0 {
		return nil
	}
	text := noticeText(typ, n, h.WebURL)
	if text == "" {
		return nil
	}
	rows, err := h.Pool.Query(ctx,
		`SELECT l.telegram_id, COALESCE(NULLIF(u.time_zone, ''), o.time_zone) FROM core.guss_links l
		 JOIN core.users u ON u.id = l.user_id JOIN core.orgs o ON o.id = l.org_id
		 WHERE l.org_id::text = $1 AND l.user_id::text = ANY($2) ORDER BY l.telegram_id`,
		orgID, n.ToUserIDs)
	if err != nil {
		return err
	}
	type target struct {
		id int64
		tz string // theirs, else the business's ("" = UTC)
	}
	var targets []target
	for rows.Next() {
		var t target
		if rows.Scan(&t.id, &t.tz) == nil {
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
		body := map[string]any{"telegram_id": t.id, "text": text, "silent": quiet(now, t.tz)}
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
