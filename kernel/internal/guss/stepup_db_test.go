package guss

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// Guss asks for a step-up for a linked person: refused without a passkey,
// then a one-time link whose page shows the action, and a status Guss can
// poll (plan 16.4). The passkey ceremony itself is go-webauthn's.
func TestStepUp(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	var orgID, userID string
	must(pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Shop', 'shop-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID))
	must(pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES ('m-' || gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&userID))
	_, err = pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'branch_manager')`, orgID, userID)
	must(err)
	_, err = pool.Exec(ctx, `INSERT INTO core.guss_links (org_id, telegram_id, user_id) VALUES ($1, 42, $2)`, orgID, userID)
	must(err)
	secret := strings.Repeat("ef", 20)
	_, err = pool.Exec(ctx, `INSERT INTO core.guss_service (org_id, token_hash) VALUES ($1, $2)`, orgID, sha(secret))
	must(err)
	key := serviceKeyPrefix + orgID + "_" + secret
	h := &Handlers{Pool: pool, WebURL: "https://friday.example/"}

	start := func(body string) (int, string) {
		r := httptest.NewRequest(http.MethodPost, "/guss/svc/step-up", bytes.NewBufferString(body))
		r.Header.Set("Authorization", "Bearer "+key)
		w := httptest.NewRecorder()
		h.StartStepUp(w, r)
		return w.Code, w.Body.String()
	}
	if c, body := start(`{"telegram_id": 42, "action": "Void #12: tv, 30000.00 KES"}`); c != http.StatusConflict || !strings.Contains(body, "passkey") {
		t.Fatalf("no passkey yet: %d %s", c, body)
	}
	if c, _ := start(`{"telegram_id": 43, "action": "x"}`); c != http.StatusNotFound {
		t.Fatalf("not linked: %d", c)
	}
	_, err = pool.Exec(ctx, `INSERT INTO core.webauthn_credentials (user_id, credential_id, public_key, sign_count, device_label) VALUES ($1, $2, $3, 0, 'test')`,
		userID, "cred-"+userID, "pk")
	must(err)
	c, body := start(`{"telegram_id": 42, "action": "Void #12: tv, 30000.00 KES"}`)
	var out struct {
		ID   string `json:"id"`
		Link string `json:"link"`
	}
	json.Unmarshal([]byte(body), &out)
	if c != 200 || !strings.HasPrefix(out.Link, "https://friday.example/step-up?c=") {
		t.Fatalf("start: %d %s", c, body)
	}
	code := strings.TrimPrefix(out.Link, "https://friday.example/step-up?c=")

	// The page shows what it's for; a wrong code shows nothing.
	ah := &auth.Handlers{Pool: pool}
	info := func(code string) (int, string) {
		w := httptest.NewRecorder()
		ah.StepUpInfo(w, httptest.NewRequest(http.MethodGet, "/auth/step-up?c="+code, nil))
		return w.Code, w.Body.String()
	}
	if c, body := info(code); c != 200 || !strings.Contains(body, "Void #12: tv") || !strings.Contains(body, `"done":false`) {
		t.Fatalf("info: %d %s", c, body)
	}
	if c, _ := info("nope"); c != http.StatusNotFound {
		t.Fatalf("wrong code: %d", c)
	}

	status := func(id string) string {
		r := httptest.NewRequest(http.MethodGet, "/guss/svc/step-up/"+id, nil)
		r.SetPathValue("id", id)
		r.Header.Set("Authorization", "Bearer "+key)
		w := httptest.NewRecorder()
		h.StepUpStatus(w, r)
		return w.Body.String()
	}
	if s := status(out.ID); !strings.Contains(s, `"done":false`) {
		t.Fatalf("status before: %s", s)
	}
	_, err = pool.Exec(ctx, `UPDATE core.step_ups SET done_at = now(), method = 'passkey' WHERE id::text = $1`, out.ID)
	must(err)
	if s := status(out.ID); !strings.Contains(s, `"done":true`) {
		t.Fatalf("status after: %s", s)
	}
	// Verifying an already confirmed check is refused before any passkey work.
	w := httptest.NewRecorder()
	ah.StepUpVerify(w, httptest.NewRequest(http.MethodPost, "/auth/step-up/verify?c="+code+"&session_id=x", nil))
	if w.Code != http.StatusConflict {
		t.Fatalf("verify twice: %d %s", w.Code, w.Body.String())
	}
}
