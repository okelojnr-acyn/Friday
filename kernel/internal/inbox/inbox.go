// Package inbox is the notification inbox (HR plan 8.4.1): what the kernel
// tells people about events (a claim waiting for them, a decision on
// theirs), kept per person and business, shown as a bell in Friday and in
// Minions. The same message goes out on Guss (internal/guss.Notify).
package inbox

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Notice is what an event names: who to tell and the facts to say.
type Notice struct {
	ToUserIDs     []string `json:"to_user_ids"`
	Kind          string   `json:"kind"` // approval.needed: expense_claim, salary_advance, time_off, spend_request or trip
	FromName      string   `json:"from_name"`
	AmountCents   int64    `json:"amount_cents"`
	Currency      string   `json:"currency"`
	Description   string   `json:"description"`
	Status        string   `json:"status"`
	Note          string   `json:"note"`
	DecidedByName string   `json:"decided_by_name"`
	Method        string   `json:"method"`
	// Tasks (projects.task.*).
	Task         string `json:"task"`
	AssigneeName string `json:"assignee_name"`
	Level        int    `json:"level"` // overdue: 1 on the due day, 2 three days later
	// Meetings (minions.meeting.*).
	Meeting  string `json:"meeting"`
	StartsAt string `json:"starts_at"`
	Response string `json:"response"`
	ByName   string `json:"by_name"`
}

// When: "Thu 27 Nov, 10:00" in loc (the business's zone; UTC if nil).
func When(iso string, loc *time.Location) string {
	t, err := time.Parse(time.RFC3339Nano, iso)
	if err != nil {
		return ""
	}
	if loc == nil {
		loc = time.UTC
	}
	return t.In(loc).Format("Mon 2 Jan, 15:04")
}

// Message is one notice in words, with where it leads: StaffPath in
// Minions, DeskPath in Friday (owners, admins, branch managers).
type Message struct {
	Title, Body, StaffPath, DeskPath string
}

// Money: "KES 1,500" (cents shown only when there are some).
func Money(cents int64, currency string) string {
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

// Compose turns an event into its message; ok=false for events that say
// nothing to people. shortcut: English only; follow the business's
// language when asked.
func Compose(typ string, n Notice, loc *time.Location) (Message, bool) {
	amount, what := Money(n.AmountCents, n.Currency), strings.TrimSpace(n.Description)
	meeting := strings.TrimSpace(n.Meeting) + ", " + When(n.StartsAt, loc)
	switch typ {
	case "minions.meeting.invited":
		return Message{n.FromName + " invited you to a meeting", meeting, "/minions/calendar", "/people/meeting"}, true
	case "minions.meeting.changed":
		return Message{"A meeting moved", strings.TrimSpace(n.Meeting) + ", now " + When(n.StartsAt, loc), "/minions/calendar", "/people/meeting"}, true
	case "minions.meeting.soon":
		return Message{"Starting in 30 minutes", meeting, "/minions/calendar", "/people/meeting"}, true
	case "minions.meeting.cancelled":
		return Message{n.FromName + " cancelled a meeting", meeting, "/minions/calendar", "/people/meeting"}, true
	case "minions.meeting.answered":
		verb := map[string]string{"accepted": "accepted", "declined": "declined"}[n.Response]
		if verb == "" {
			return Message{}, false
		}
		return Message{n.ByName + " " + verb + " your meeting", meeting, "/minions/calendar", "/people/meeting"}, true
	case "minions.approval.needed":
		if n.Kind == "time_off" {
			return Message{n.FromName + " asks for time off", what, "/minions/team", "/people/time_off"}, true
		}
		if n.Kind == "spend_request" || n.Kind == "trip" {
			ask := map[string]string{"spend_request": " asks first to spend", "trip": " asks to go on a trip"}[n.Kind]
			return Message{n.FromName + ask, amount + " for " + what, "/minions/team", "/minions/team"}, true
		}
		if n.Kind == "salary_advance" {
			body := amount
			if what != "" {
				body += " for " + what
			}
			return Message{n.FromName + " asks for a salary advance", body, "/minions/team", "/people/salary_advance"}, true
		}
		return Message{n.FromName + " asks you to approve a claim", amount + " for " + what,
			"/minions/team", "/people/expense_claim"}, true
	case "minions.salary_advance.decided":
		if n.Status == "rejected" {
			return Message{n.DecidedByName + " turned down your salary advance", amount + ": " + n.Note,
				"/minions/payroll", "/minions/payroll"}, true
		}
		return Message{n.DecidedByName + " approved your salary advance", amount, "/minions/payroll", "/minions/payroll"}, true
	case "minions.announcement.posted":
		return Message{"Announcement from " + n.FromName, what, "/minions/", "/minions/"}, true
	case "minions.cover.set":
		return Message{n.FromName + " asked you to approve for them", "While they're away, " + what + ". Their requests come to you.", "/minions/team", "/minions/team"}, true
	case "minions.time_off.decided":
		if n.Status == "rejected" {
			return Message{n.DecidedByName + " turned down your time off", what + ": " + n.Note, "/minions/calendar", "/minions/calendar"}, true
		}
		return Message{n.DecidedByName + " approved your time off", what, "/minions/calendar", "/minions/calendar"}, true
	case "minions.spend_request.decided":
		if n.Status == "rejected" {
			return Message{n.DecidedByName + " turned down your request", what + " (" + amount + "): " + n.Note,
				"/minions/expense-claims", "/minions/expense-claims"}, true
		}
		return Message{n.DecidedByName + " approved your request", what + " (" + amount + "). Claim against it when you spend.",
			"/minions/expense-claims", "/minions/expense-claims"}, true
	case "minions.trip_advance.paid":
		how := map[string]string{"mpesa": " by M-Pesa", "bank": " by bank transfer", "cash": " in cash"}[n.Method]
		return Message{"Your trip advance was paid", amount + how + ". Claim the trip's spends against it.",
			"/minions/expense-claims", "/minions/expense-claims"}, true
	case "minions.trip.settled":
		return Message{"Your trip was settled", what, "/minions/expense-claims", "/minions/expense-claims"}, true
	case "minions.salary_advance.paid":
		how := map[string]string{"mpesa": " by M-Pesa", "bank": " by bank transfer", "cash": " in cash", "crypto": " to your wallet"}[n.Method]
		return Message{"Your salary advance was paid", amount + how + ". It comes off your next pay.", "/minions/payroll", "/minions/payroll"}, true
	case "minions.expense_claim.decided":
		if n.Status == "rejected" {
			return Message{n.DecidedByName + " rejected your claim",
				fmt.Sprintf("%s (%s): %s. Fix it and send it again.", what, amount, n.Note),
				"/minions/expense-claims", "/minions/expense-claims"}, true
		}
		return Message{n.DecidedByName + " approved your claim", fmt.Sprintf("%s (%s)", what, amount),
			"/minions/expense-claims", "/minions/expense-claims"}, true
	case "projects.task.assigned":
		return Message{n.FromName + " gave you a task", n.Task, "/minions/", "/projects/task"}, true
	case "projects.task.done":
		return Message{n.FromName + " finished a task", n.Task, "/minions/team", "/projects/task"}, true
	case "projects.task.overdue":
		if n.Level >= 2 {
			return Message{"A task in your team is 3 days overdue", n.Task + ", given to " + n.AssigneeName,
				"/minions/team", "/projects/task"}, true
		}
		return Message{"A task is overdue", n.Task + ", given to " + n.AssigneeName, "/minions/", "/projects/task"}, true
	case "minions.expense_claim.paid":
		how := map[string]string{"mpesa": " by M-Pesa", "bank": " by bank transfer", "cash": " in cash", "crypto": " to your wallet"}[n.Method]
		return Message{"Your claim was paid", fmt.Sprintf("%s (%s)%s.", what, amount, how),
			"/minions/expense-claims", "/minions/expense-claims"}, true
	}
	return Message{}, false
}

// Zone is the named time zone, or nil (UTC) for "" or an unknown name.
func Zone(name string) *time.Location {
	if name == "" {
		return nil
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		return nil
	}
	return loc
}

// deskRoles work in Friday's own screens; everyone else in Minions.
var deskRoles = map[string]bool{"owner": true, "admin": true, "branch_manager": true, "viewer": true}

// Inbox stores and serves notices.
type Inbox struct {
	Pool *pgxpool.Pool
}

// Deliver files the event's notice for each person it names, once per
// event (a retried delivery adds nothing). Unknown events are skipped.
func (in *Inbox) Deliver(ctx context.Context, eventID, orgID, typ string, payload []byte) error {
	var n Notice
	if json.Unmarshal(payload, &n) != nil || len(n.ToUserIDs) == 0 {
		return nil
	}
	var tz string
	_ = in.Pool.QueryRow(ctx, `SELECT time_zone FROM core.orgs WHERE id::text = $1`, orgID).Scan(&tz)
	m, ok := Compose(typ, n, Zone(tz))
	if !ok {
		return nil
	}
	_, err := in.Pool.Exec(ctx, `
		INSERT INTO core.notifications (org_id, user_id, event_id, kind, title, body, link)
		SELECT m.org_id, m.user_id, $3, $4, $5, $6,
		       CASE WHEN m.role IN ('owner', 'admin', 'branch_manager', 'viewer') THEN $8 ELSE $7 END
		FROM core.memberships m WHERE m.org_id::text = $1 AND m.user_id::text = ANY($2)
		ON CONFLICT (event_id, user_id) DO NOTHING`,
		orgID, n.ToUserIDs, eventID, typ, m.Title, m.Body, m.StaffPath, m.DeskPath)
	return err
}

// Path is where a person with `role` should go for m.
func (m Message) Path(role string) string {
	if deskRoles[role] {
		return m.DeskPath
	}
	return m.StaffPath
}

type item struct {
	ID        int64   `json:"id"`
	Kind      string  `json:"kind"`
	Title     string  `json:"title"`
	Body      string  `json:"body"`
	Link      string  `json:"link"`
	CreatedAt string  `json:"created_at"`
	ReadAt    *string `json:"read_at"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

// List (GET /me/notifications): my latest 30 here, and how many are unread.
func (in *Inbox) List(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	ctx := r.Context()
	var unread int
	if err := in.Pool.QueryRow(ctx, `SELECT count(*) FROM core.notifications WHERE user_id::text = $1 AND org_id::text = $2 AND read_at IS NULL`,
		c.Subject, c.OrgID).Scan(&unread); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "couldn't load notifications"})
		return
	}
	rows, err := in.Pool.Query(ctx, `
		SELECT id, kind, title, body, link, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
		       CASE WHEN read_at IS NULL THEN NULL ELSE to_char(read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') END
		FROM core.notifications WHERE user_id::text = $1 AND org_id::text = $2
		ORDER BY created_at DESC, id DESC LIMIT 30`, c.Subject, c.OrgID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "couldn't load notifications"})
		return
	}
	defer rows.Close()
	items := []item{}
	for rows.Next() {
		var it item
		if rows.Scan(&it.ID, &it.Kind, &it.Title, &it.Body, &it.Link, &it.CreatedAt, &it.ReadAt) == nil {
			items = append(items, it)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"unread": unread, "items": items})
}

// Read (POST /me/notifications/read, {"ids": [...]} or {"all": true}):
// marks my notices read.
func (in *Inbox) Read(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	var req struct {
		IDs []int64 `json:"ids"`
		All bool    `json:"all"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil || (!req.All && len(req.IDs) == 0) || len(req.IDs) > 200 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": `send {"ids": [...]} or {"all": true}`})
		return
	}
	_, err := in.Pool.Exec(r.Context(), `
		UPDATE core.notifications SET read_at = now()
		WHERE user_id::text = $1 AND org_id::text = $2 AND read_at IS NULL AND ($3 OR id = ANY($4))`,
		c.Subject, c.OrgID, req.All, req.IDs)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "couldn't save"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
