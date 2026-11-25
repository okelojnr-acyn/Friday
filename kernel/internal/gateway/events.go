package gateway

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

type inboundEvent struct {
	// ID is the publisher's event id (friday_common.events.publish_event);
	// a resent event with the same id is queued once. Older publishers
	// send none and get one here.
	ID      string          `json:"id"`
	Type    string          `json:"type"`
	OrgID   string          `json:"org_id"`
	Payload json.RawMessage `json:"payload"`
	// DeliverAt, if set, holds the event until then (at most maxAhead).
	DeliverAt *time.Time `json:"deliver_at"`
}

// maxAhead: how far ahead an event may be scheduled.
const maxAhead = 400 * 24 * time.Hour

// wake tells this kernel's Deliverer an event just arrived, so it's sent at
// once instead of at the next idle check.
var wake = make(chan struct{}, 1)

// subscription is the one cross-app wiring rule in the system: when
// `Event` fires, POST the payload to `App`'s webhook path. Deliberately a
// short static list, not a dynamic pub/sub registry -- see
// ARCHITECTURE.md for why. Add a line here when a new app needs to react
// to another app's event.
type subscription struct {
	Event       string
	App         string
	WebhookPath string
}

var subscriptions = []subscription{
	{Event: "crm.opportunity.won", App: "invoicing", WebhookPath: "/internal/webhooks/crm-won"},
	{Event: "invoicing.pos_sale.recorded", App: "inventory", WebhookPath: "/internal/webhooks/pos-sale"},
	{Event: "invoicing.invoice.paid", App: "accounting", WebhookPath: "/internal/webhooks/invoice-paid"},
	{Event: "invoicing.pos_sale.recorded", App: "accounting", WebhookPath: "/internal/webhooks/pos-sale-cogs"},
	{Event: "invoicing.pos_sale.recorded", App: "minions", WebhookPath: "/internal/webhooks/pos-sale"},
	{Event: "minions.payroll_run.paid", App: "accounting", WebhookPath: "/internal/webhooks/payroll-paid"},
	{Event: "minions.expense_claim.paid", App: "accounting", WebhookPath: "/internal/webhooks/claim-paid"},
	{Event: "inventory.purchase.received", App: "accounting", WebhookPath: "/internal/webhooks/purchase-received"},
	{Event: "inventory.purchase.paid", App: "accounting", WebhookPath: "/internal/webhooks/purchase-paid"},
	{Event: "inventory.stock.adjusted", App: "accounting", WebhookPath: "/internal/webhooks/stock-adjusted"},
	// Tell people: their inbox (the bell) and Guss (Deliverer.Local["notify"]).
	{Event: "minions.approval.needed", App: "notify"},
	{Event: "minions.expense_claim.decided", App: "notify"},
	{Event: "minions.expense_claim.paid", App: "notify"},
	{Event: "projects.task.assigned", App: "notify"},
	{Event: "projects.task.done", App: "notify"},
	{Event: "projects.task.overdue", App: "notify"},
	// Scheduled for a task's due time (and 3 days later): Projects checks it.
	{Event: "projects.task.due", App: "projects", WebhookPath: "/internal/webhooks/task-due"},
}


func newEventID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// EventsHandler receives events apps publish and queues one delivery per
// subscriber in core.event_deliveries. It answers 202 only once they are
// stored, so the publisher's outbox keeps retrying until then; Deliverer
// sends them. (Before 2026-11-16 each was sent in a fire-and-forget
// goroutine, and a failure was only logged.)
func EventsHandler(pool *pgxpool.Pool, eventsToken string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !svcauth.Bearer(r, eventsToken) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		var ev inboundEvent
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&ev); err != nil || ev.Type == "" || ev.OrgID == "" {
			http.Error(w, "invalid event body", http.StatusBadRequest)
			return
		}
		if ev.ID == "" {
			ev.ID = newEventID()
		}
		if len(ev.Payload) == 0 {
			ev.Payload = json.RawMessage("{}")
		}
		if ev.DeliverAt != nil && (ev.DeliverAt.After(time.Now().Add(maxAhead)) || ev.DeliverAt.Before(time.Now())) {
			if ev.DeliverAt.Before(time.Now()) {
				ev.DeliverAt = nil // already due: now
			} else {
				http.Error(w, "deliver_at is at most 400 days ahead", http.StatusBadRequest)
				return
			}
		}
		ctx := r.Context()
		tx, err := pool.Begin(ctx)
		if err != nil {
			http.Error(w, "could not queue the event", http.StatusServiceUnavailable)
			return
		}
		defer tx.Rollback(ctx)
		for _, sub := range subscriptions {
			if sub.Event != ev.Type {
				continue
			}
			if _, err := tx.Exec(ctx, `
				INSERT INTO core.event_deliveries (event_id, type, org_id, payload, app, webhook_path, next_attempt_at, scheduled_for)
				VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, now()), $7) ON CONFLICT (event_id, app, webhook_path) DO NOTHING`,
				ev.ID, ev.Type, ev.OrgID, []byte(ev.Payload), sub.App, sub.WebhookPath, ev.DeliverAt); err != nil {
				log.Printf("event %s: queue for %s: %v", ev.Type, sub.App, err)
				http.Error(w, "could not queue the event", http.StatusServiceUnavailable)
				return
			}
		}
		if err := tx.Commit(ctx); err != nil {
			http.Error(w, "could not queue the event", http.StatusServiceUnavailable)
			return
		}
		if ev.DeliverAt == nil {
			select {
			case wake <- struct{}{}:
			default:
			}
		}
		w.WriteHeader(http.StatusAccepted)
	}
}

// Deliverer sends queued events to subscribers, retrying with backoff
// (5 s, 10 s, 20 s ... up to an hour) until each accepts.
type Deliverer struct {
	Pool   *pgxpool.Pool
	Apps   []registry.App
	Token  string
	Client *http.Client
	// Every is how often the queue is checked (2 s by default).
	Every time.Duration
	// Local subscribers the kernel runs itself, by App name ("notify":
	// Guss notices), with the same retries as an app's webhook.
	Local map[string]func(ctx context.Context, eventID, orgID, typ string, payload []byte) error
}

func backoff(attempts int) time.Duration {
	if attempts < 1 {
		attempts = 1
	}
	if attempts > 12 {
		return time.Hour
	}
	d := 5 * time.Second << (attempts - 1)
	if d > time.Hour {
		return time.Hour
	}
	return d
}

type delivery struct {
	id                             int64
	eventID, typ, orgID, app, path string
	payload                        []byte
	attempts                       int
}

// DeliverDue sends what is due now and returns how many were delivered.
// Rows are leased for a minute while being sent, so two kernels never
// send the same delivery at once.
func (d *Deliverer) DeliverDue(ctx context.Context) (int, error) {
	rows, err := d.Pool.Query(ctx, `
		UPDATE core.event_deliveries SET next_attempt_at = now() + interval '1 minute', attempts = attempts + 1
		WHERE id IN (SELECT id FROM core.event_deliveries WHERE delivered_at IS NULL AND next_attempt_at <= now()
		             ORDER BY id LIMIT 50 FOR UPDATE SKIP LOCKED)
		RETURNING id, event_id, type, org_id, payload, app, webhook_path, attempts`)
	if err != nil {
		return 0, err
	}
	var due []delivery
	for rows.Next() {
		var x delivery
		if err := rows.Scan(&x.id, &x.eventID, &x.typ, &x.orgID, &x.payload, &x.app, &x.path, &x.attempts); err != nil {
			rows.Close()
			return 0, err
		}
		due = append(due, x)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}

	base := map[string]string{}
	for _, a := range d.Apps {
		base[a.Name] = strings.TrimRight(a.BaseURL, "/")
	}
	client := d.Client
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	delivered := 0
	for _, x := range due {
		var err error
		if local, ok := d.Local[x.app]; ok {
			err = local(ctx, x.eventID, x.orgID, x.typ, x.payload)
		} else {
			err = d.send(ctx, client, base[x.app], x)
		}
		if err != nil {
			log.Printf("event %s to %s not delivered (try %d): %v", x.typ, x.app, x.attempts, err)
			_, _ = d.Pool.Exec(ctx, `UPDATE core.event_deliveries SET next_attempt_at = now() + make_interval(secs => $2), last_error = $3 WHERE id = $1`,
				x.id, backoff(x.attempts).Seconds(), truncate(err.Error(), 500))
			continue
		}
		delivered++
		_, _ = d.Pool.Exec(ctx, `UPDATE core.event_deliveries SET delivered_at = now(), last_error = '' WHERE id = $1`, x.id)
	}
	return delivered, nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func (d *Deliverer) send(ctx context.Context, client *http.Client, base string, x delivery) error {
	if base == "" {
		return fmt.Errorf("app %q isn't registered", x.app)
	}
	body, _ := json.Marshal(map[string]any{
		"id": x.eventID, "type": x.typ, "org_id": x.orgID, "payload": json.RawMessage(x.payload),
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+x.path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+d.Token)
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 300))
		return fmt.Errorf("%s: %s", resp.Status, strings.TrimSpace(string(msg)))
	}
	return nil
}

// Run delivers until ctx ends, and trims delivered rows older than a week.
func (d *Deliverer) Run(ctx context.Context) {
	// Idle check for retries and scheduled events; a new event wakes it.
	every := d.Every
	if every == 0 {
		every = 15 * time.Second
	}
	t := time.NewTicker(every)
	defer t.Stop()
	var lastTrim time.Time
	for {
		for {
			n, err := d.DeliverDue(ctx)
			if err != nil {
				log.Printf("event deliveries: %v", err)
			}
			if n == 0 || err != nil {
				break
			}
		}
		if time.Since(lastTrim) > time.Hour {
			_, _ = d.Pool.Exec(ctx, `DELETE FROM core.event_deliveries WHERE delivered_at < now() - interval '7 days'`)
			TrimExpired(ctx, d.Pool)
			lastTrim = time.Now()
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		case <-wake:
		}
	}
}

// EventCounts reports undelivered events, and how many are stuck (older
// than 10 minutes), for the health check.
func EventCounts(pool *pgxpool.Pool) func(ctx context.Context) (pending, stuck int, err error) {
	return func(ctx context.Context) (int, int, error) {
		var pending, stuck int
		err := pool.QueryRow(ctx, `
			SELECT count(*), count(*) FILTER (WHERE COALESCE(scheduled_for, created_at) < now() - interval '10 minutes')
			FROM core.event_deliveries WHERE delivered_at IS NULL AND (scheduled_for IS NULL OR scheduled_for <= now())`).Scan(&pending, &stuck)
		return pending, stuck, err
	}
}

// Rows that only matter for a short while, cleared hourly so tables don't
// grow with every sign-in (RELIABILITY-PLAN retention, owner 2026-11-23).
// Sales, the books and tax records are never cleared here.
var trimStatements = []string{
	`DELETE FROM core.otp_codes WHERE expires_at < now() - interval '7 days'`,
	`DELETE FROM core.webauthn_challenges WHERE expires_at < now() - interval '1 day'`,
	`DELETE FROM core.step_ups WHERE expires_at < now() - interval '7 days'`,
	`DELETE FROM core.guss_link_codes WHERE expires_at < now() - interval '1 day'`,
	`DELETE FROM core.guss_web_codes WHERE expires_at < now() - interval '1 day'`,
	`DELETE FROM core.pos_pin_events WHERE created_at < now() - interval '2 years'`,
	`DELETE FROM core.sessions WHERE created_at < now() - interval '30 days'`,
	`DELETE FROM core.notifications WHERE created_at < now() - interval '90 days'`,
}

// TrimExpired runs trimStatements; a failure is logged and the rest still run.
func TrimExpired(ctx context.Context, pool *pgxpool.Pool) {
	for _, q := range trimStatements {
		if _, err := pool.Exec(ctx, q); err != nil {
			log.Printf("trim: %v", err)
		}
	}
}
