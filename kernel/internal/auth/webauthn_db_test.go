package auth

// Passkey registration against a real Postgres (plan section 11). Runs
// when KERNEL_TEST_DATABASE_URL is set (CI's kernel job sets it); skips
// otherwise, so `go test ./...` on a laptop without Postgres still passes.

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/go-webauthn/webauthn/webauthn"
	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
)

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	url := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	return pool
}

func randHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// newOrg makes an org and returns its id.
func newOrg(t *testing.T, pool *pgxpool.Pool) string {
	t.Helper()
	var id string
	s := "t-" + randHex(6)
	if err := pool.QueryRow(context.Background(),
		`INSERT INTO core.orgs (name, slug) VALUES ($1, $1) RETURNING id::text`, s).Scan(&id); err != nil {
		t.Fatal(err)
	}
	return id
}

func testHandlers(t *testing.T, pool *pgxpool.Pool) *Handlers {
	t.Helper()
	wa, err := NewWebAuthn("localhost", "Friday", []string{"http://localhost:5173"})
	if err != nil {
		t.Fatal(err)
	}
	return &Handlers{Pool: pool, WebAuthn: wa}
}

func claimsFor(sub, orgID, email string) *Claims {
	return &Claims{OrgID: orgID, Role: "owner", Email: email, RegisteredClaims: jwt.RegisteredClaims{Subject: sub}}
}

func fakeCred() *webauthn.Credential {
	b := make([]byte, 32)
	_, _ = rand.Read(b)
	return &webauthn.Credential{ID: b, PublicKey: []byte("pk-" + randHex(4)), Authenticator: webauthn.Authenticator{SignCount: 1}}
}

func countCreds(t *testing.T, pool *pgxpool.Pool, userID string) int {
	t.Helper()
	var n int
	if err := pool.QueryRow(context.Background(),
		`SELECT count(*) FROM core.webauthn_credentials WHERE user_id = $1`, userID).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

// A cashier who joined at the till (PosVerifyCode -> joinOrg) has no full
// name; registering twice on one device keeps one row, not a "db error".
func TestRegisterTwiceOnOneDeviceAfterPosJoin(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	ctx := context.Background()
	orgID := newOrg(t, pool)
	email := "cashier-" + randHex(4) + "@example.com"
	userID, err := h.joinOrg(ctx, email, "", orgID, "member")
	if err != nil {
		t.Fatal(err)
	}

	user, err := resolveWebauthnUser(ctx, pool, claimsFor(userID, orgID, email))
	if err != nil {
		t.Fatal(err)
	}
	if user.WebAuthnDisplayName() != email {
		t.Fatalf("display name should fall back to the email, got %q", user.WebAuthnDisplayName())
	}

	cred := fakeCred()
	if err := storeWebauthnCredential(ctx, pool, userID, cred, "Till 1"); err != nil {
		t.Fatal(err)
	}
	cred.Authenticator.SignCount = 7
	if err := storeWebauthnCredential(ctx, pool, userID, cred, ""); err != nil {
		t.Fatalf("second registration of the same credential: %v", err)
	}
	if n := countCreds(t, pool, userID); n != 1 {
		t.Fatalf("want 1 credential row, got %d", n)
	}
	var label string
	var sc int64
	_ = pool.QueryRow(ctx, `SELECT device_label, sign_count FROM core.webauthn_credentials WHERE user_id = $1`, userID).Scan(&label, &sc)
	if label != "Till 1" || sc != 7 {
		t.Fatalf("want label kept and sign count refreshed, got %q %d", label, sc)
	}

	// The next ceremony excludes the credential already on the device.
	user, _ = resolveWebauthnUser(ctx, pool, claimsFor(userID, orgID, email))
	creation, _, err := h.WebAuthn.BeginRegistration(user,
		webauthn.WithExclusions(webauthn.Credentials(user.credentials).CredentialDescriptors()))
	if err != nil {
		t.Fatal(err)
	}
	if len(creation.Response.CredentialExcludeList) != 1 {
		t.Fatalf("want 1 excluded credential, got %d", len(creation.Response.CredentialExcludeList))
	}
}

func TestSameCredentialForAnotherPersonIsRefused(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	ctx := context.Background()
	orgID := newOrg(t, pool)
	a, err := h.joinOrg(ctx, "a-"+randHex(4)+"@example.com", "A", orgID, "member")
	if err != nil {
		t.Fatal(err)
	}
	b, err := h.joinOrg(ctx, "b-"+randHex(4)+"@example.com", "B", orgID, "member")
	if err != nil {
		t.Fatal(err)
	}
	cred := fakeCred()
	if err := storeWebauthnCredential(ctx, pool, a, cred, ""); err != nil {
		t.Fatal(err)
	}
	if err := storeWebauthnCredential(ctx, pool, b, cred, ""); !errors.Is(err, errCredentialTaken) {
		t.Fatalf("want errCredentialTaken, got %v", err)
	}
	if countCreds(t, pool, a) != 1 || countCreds(t, pool, b) != 0 {
		t.Fatal("the first person's credential must stay theirs")
	}
}

// The owner's 2026-11-15 failure: a Friday Host SSO token whose subject
// is a Friday Host user id unknown here.
func TestFridayHostSSOTokenResolvesByEmailWithinItsOrg(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	ctx := context.Background()
	orgID := newOrg(t, pool)
	email := "Owner-" + randHex(4) + "@Example.com"
	kernelID, err := h.joinOrg(ctx, email, "Owner", orgID, "owner")
	if err != nil {
		t.Fatal(err)
	}
	fhSubject := "00000000-0000-4000-8000-" + randHex(6)

	user, err := resolveWebauthnUser(ctx, pool, claimsFor(fhSubject, orgID, "owner"+email[5:]))
	if err != nil {
		t.Fatalf("SSO token should resolve by email: %v", err)
	}
	if user.id != kernelID {
		t.Fatalf("want kernel user %s, got %s", kernelID, user.id)
	}

	otherOrg := newOrg(t, pool)
	if _, err := resolveWebauthnUser(ctx, pool, claimsFor(fhSubject, otherOrg, email)); !errors.Is(err, errNoKernelAccount) {
		t.Fatalf("an email outside the token's org must not resolve, got %v", err)
	}
	if _, err := resolveWebauthnUser(ctx, pool, claimsFor("not-a-uuid", orgID, "nobody@example.com")); !errors.Is(err, errNoKernelAccount) {
		t.Fatalf("unknown person: want errNoKernelAccount, got %v", err)
	}

	// Through the handler: options start, the challenge is stored, and an
	// unknown person gets a 409 that says what to do, not "db error".
	call := func(c *Claims) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/auth/passkey/register-options?purpose=pos", nil)
		req = req.WithContext(WithClaims(req.Context(), c))
		rec := httptest.NewRecorder()
		h.PasskeyRegisterOptions(rec, req)
		return rec
	}
	if rec := call(claimsFor(fhSubject, orgID, email)); rec.Code != http.StatusOK {
		t.Fatalf("register-options for an SSO owner: %d %s", rec.Code, rec.Body)
	}
	rec := call(claimsFor(fhSubject, orgID, "stranger@example.com"))
	var body map[string]string
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	if rec.Code != http.StatusConflict || body["error"] == "db error" {
		t.Fatalf("unknown person: want 409 with guidance, got %d %v", rec.Code, body)
	}
}
