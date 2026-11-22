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

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// The whole link: Guss asks for a code with its service key, the person
// enters it in Friday, they're linked; a used, mistyped or expired code
// says which (owner, 2026-11-22: "linking by code fails or says expired").
func TestLinkByCode(t *testing.T) {
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
	must(pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES ('o-' || gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&userID))
	_, err = pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'owner')`, orgID, userID)
	must(err)
	secret := strings.Repeat("ab", 20)
	_, err = pool.Exec(ctx, `INSERT INTO core.guss_service (org_id, token_hash) VALUES ($1, $2)`, orgID, sha(secret))
	must(err)
	key := serviceKeyPrefix + orgID + "_" + secret

	h := &Handlers{Pool: pool}
	issue := func(tg int64) string {
		r := httptest.NewRequest(http.MethodPost, "/guss/svc/link-code", bytes.NewBufferString(`{"telegram_id": `+jsonInt(tg)+`, "name": "Fire"}`))
		r.Header.Set("Authorization", "Bearer "+key)
		w := httptest.NewRecorder()
		h.LinkCode(w, r)
		if w.Code != 200 {
			t.Fatalf("link code: %d %s", w.Code, w.Body.String())
		}
		var out struct {
			Code      string `json:"code"`
			ExpiresIn int    `json:"expires_in"`
		}
		json.Unmarshal(w.Body.Bytes(), &out)
		if len(out.Code) != 6 || out.ExpiresIn != 1800 {
			t.Fatalf("code %q lasts %d s", out.Code, out.ExpiresIn)
		}
		return out.Code
	}
	enter := func(code string) (int, string) {
		r := httptest.NewRequest(http.MethodPost, "/guss/link", bytes.NewBufferString(`{"code": "`+code+`"}`))
		r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: "owner", RegisteredClaims: jwt.RegisteredClaims{Subject: userID}}))
		w := httptest.NewRecorder()
		h.Link(w, r)
		return w.Code, w.Body.String()
	}

	// A wrong key gets no code.
	r := httptest.NewRequest(http.MethodPost, "/guss/svc/link-code", bytes.NewBufferString(`{"telegram_id": 7}`))
	r.Header.Set("Authorization", "Bearer "+serviceKeyPrefix+orgID+"_"+strings.Repeat("cd", 20))
	w := httptest.NewRecorder()
	h.LinkCode(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("wrong key: %d", w.Code)
	}

	code := issue(7)
	spaced := code[:3] + " " + code[3:]
	if c, body := enter(spaced); c != 200 || !strings.Contains(body, `"telegram_id":7`) {
		t.Fatalf("linking with %q: %d %s", spaced, c, body)
	}
	var linked int
	must(pool.QueryRow(ctx, `SELECT count(*) FROM core.guss_links WHERE org_id = $1 AND telegram_id = 7 AND user_id::text = $2`, orgID, userID).Scan(&linked))
	if linked != 1 {
		t.Fatal("not linked")
	}
	if c, body := enter(code); c != http.StatusNotFound || !strings.Contains(body, "doesn't match") {
		t.Fatalf("a used code: %d %s", c, body)
	}

	// Unlink, then link again with a new code (the owner's case).
	_, err = pool.Exec(ctx, `DELETE FROM core.guss_links WHERE org_id = $1`, orgID)
	must(err)
	again := issue(7)
	if c, body := enter(again); c != 200 {
		t.Fatalf("relink: %d %s", c, body)
	}

	// One tap from Friday: Guss reports its bot, Friday makes the link,
	// Guss redeems it once.
	svc := func(path, body string, hf func(http.ResponseWriter, *http.Request)) (int, string) {
		r := httptest.NewRequest(http.MethodPost, path, bytes.NewBufferString(body))
		r.Header.Set("Authorization", "Bearer "+key)
		w := httptest.NewRecorder()
		hf(w, r)
		return w.Code, w.Body.String()
	}
	webCode := func() (int, string) {
		r := httptest.NewRequest(http.MethodPost, "/guss/link-code", nil)
		r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: "owner", RegisteredClaims: jwt.RegisteredClaims{Subject: userID}}))
		w := httptest.NewRecorder()
		h.WebLinkCode(w, r)
		return w.Code, w.Body.String()
	}
	if c, _ := webCode(); c != http.StatusConflict {
		t.Fatalf("a link before Guss reported its bot: %d", c)
	}
	if c, body := svc("/guss/svc/bot", `{"username": "@DukaGussBot"}`, h.SetBot); c != http.StatusNoContent {
		t.Fatalf("set bot: %d %s", c, body)
	}
	c, body := webCode()
	var wl struct {
		Link string `json:"link"`
	}
	json.Unmarshal([]byte(body), &wl)
	if c != 200 || !strings.HasPrefix(wl.Link, "https://t.me/DukaGussBot?start=link-") {
		t.Fatalf("web link: %d %s", c, body)
	}
	tok := strings.TrimPrefix(wl.Link, "https://t.me/DukaGussBot?start=link-")
	if c, body := svc("/guss/svc/redeem", `{"code": "`+tok+`", "telegram_id": 99, "name": "Fire"}`, h.Redeem); c != 200 || !strings.Contains(body, `"guss_role":"owner"`) {
		t.Fatalf("redeem: %d %s", c, body)
	}
	must(pool.QueryRow(ctx, `SELECT count(*) FROM core.guss_links WHERE org_id = $1 AND telegram_id = 99 AND user_id::text = $2`, orgID, userID).Scan(&linked))
	if linked != 1 {
		t.Fatal("not linked by the web code")
	}
	if c, _ := svc("/guss/svc/redeem", `{"code": "`+tok+`", "telegram_id": 99, "name": "Fire"}`, h.Redeem); c != http.StatusNotFound {
		t.Fatalf("a used web code: %d", c)
	}

	// An expired code says it expired.
	old := issue(8)
	_, err = pool.Exec(ctx, `UPDATE core.guss_link_codes SET expires_at = now() - interval '1 minute' WHERE org_id = $1 AND telegram_id = 8`, orgID)
	must(err)
	if c, body := enter(old); c != http.StatusGone || !strings.Contains(body, "expired") {
		t.Fatalf("expired code: %d %s", c, body)
	}

	// People tells Guss who reports to whom (team leaders' approvals).
	var staffID string
	must(pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES ('s-' || gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&staffID))
	_, err = pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role, reports_to) VALUES ($1, $2, 'member', $3)`, orgID, staffID, userID)
	must(err)
	_, err = pool.Exec(ctx, `INSERT INTO core.guss_links (org_id, telegram_id, user_id) VALUES ($1, 55, $2)`, orgID, staffID)
	must(err)
	r = httptest.NewRequest(http.MethodGet, "/guss/svc/people", nil)
	r.Header.Set("Authorization", "Bearer "+key)
	w = httptest.NewRecorder()
	h.People(w, r)
	var ppl struct {
		People []linkView `json:"people"`
	}
	json.Unmarshal(w.Body.Bytes(), &ppl)
	found := false
	for _, p := range ppl.People {
		if p.TelegramID == 55 {
			found = p.ReportsTo == userID && p.GussRole == "staff"
		}
	}
	if !found {
		t.Fatalf("people: %s", w.Body.String())
	}
}

func jsonInt(n int64) string {
	b, _ := json.Marshal(n)
	return string(b)
}
