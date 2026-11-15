package gateway

// Durable event delivery against a real Postgres (plan section 13).

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

func eventsPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `DELETE FROM core.event_deliveries`); err != nil {
		t.Fatal(err)
	}
	return pool
}

func publish(t *testing.T, h http.HandlerFunc, body string) int {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/internal/events", bytes.NewBufferString(body))
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	h(rec, req)
	return rec.Code
}

// A subscriber that's down gets the event when it's back; a resent event
// is queued once; each subscriber is delivered to on its own.
func TestEventsAreKeptUntilEachSubscriberTakesThem(t *testing.T) {
	pool := eventsPool(t)
	ctx := context.Background()

	var mu sync.Mutex
	got := map[string][]string{}
	inventoryDown := true
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if r.Header.Get("Authorization") != "Bearer tok" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if r.URL.Path == "/inv/internal/webhooks/pos-sale" && inventoryDown {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		got[r.URL.Path] = append(got[r.URL.Path], r.URL.Path)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()
	apps := []registry.App{
		{Name: "inventory", BaseURL: srv.URL + "/inv"},
		{Name: "accounting", BaseURL: srv.URL + "/acc"},
		{Name: "minions", BaseURL: srv.URL + "/min"},
	}
	h := EventsHandler(pool, "tok")
	sale := `{"id":"evt-1","type":"invoicing.pos_sale.recorded","org_id":"o1","payload":{"invoice_number":"POS-1"}}`
	if code := publish(t, h, sale); code != http.StatusAccepted {
		t.Fatalf("publish: %d", code)
	}
	if code := publish(t, h, sale); code != http.StatusAccepted { // the publisher's retry
		t.Fatalf("republish: %d", code)
	}
	var queued int
	pool.QueryRow(ctx, `SELECT count(*) FROM core.event_deliveries WHERE event_id = 'evt-1'`).Scan(&queued)
	if queued != 3 {
		t.Fatalf("want one delivery per subscriber (3), got %d", queued)
	}

	d := &Deliverer{Pool: pool, Apps: apps, Token: "tok"}
	if n, err := d.DeliverDue(ctx); err != nil || n != 2 {
		t.Fatalf("first pass: delivered %d, %v", n, err)
	}
	var lastErr string
	var later bool
	pool.QueryRow(ctx, `SELECT last_error, next_attempt_at > now() FROM core.event_deliveries WHERE app = 'inventory'`).Scan(&lastErr, &later)
	if lastErr == "" || !later {
		t.Fatalf("inventory's failure should be recorded and retried later: %q %v", lastErr, later)
	}

	mu.Lock()
	inventoryDown = false
	mu.Unlock()
	pool.Exec(ctx, `UPDATE core.event_deliveries SET next_attempt_at = now() WHERE delivered_at IS NULL`)
	if n, err := d.DeliverDue(ctx); err != nil || n != 1 {
		t.Fatalf("retry: delivered %d, %v", n, err)
	}
	if n, _ := d.DeliverDue(ctx); n != 0 {
		t.Fatalf("nothing should be sent twice, sent %d", n)
	}
	mu.Lock()
	defer mu.Unlock()
	for _, p := range []string{"/inv/internal/webhooks/pos-sale", "/acc/internal/webhooks/pos-sale-cogs", "/min/internal/webhooks/pos-sale"} {
		if len(got[p]) != 1 {
			t.Errorf("%s got %d deliveries, want 1", p, len(got[p]))
		}
	}
	pending, stuck, err := EventCounts(pool)(ctx)
	if err != nil || pending != 0 || stuck != 0 {
		t.Fatalf("counts: %d %d %v", pending, stuck, err)
	}
}

func TestEventsNeedTheToken(t *testing.T) {
	h := EventsHandler(nil, "tok")
	req := httptest.NewRequest(http.MethodPost, "/internal/events", bytes.NewBufferString(`{}`))
	rec := httptest.NewRecorder()
	h(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("got %d", rec.Code)
	}
}

func TestBackoffGrowsToAnHour(t *testing.T) {
	if backoff(1).Seconds() != 5 || backoff(2).Seconds() != 10 || backoff(30).Hours() != 1 {
		t.Fatal("backoff")
	}
}
