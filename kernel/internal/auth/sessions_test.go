package auth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/golang-jwt/jwt/v5"
)

func TestDeviceLabel(t *testing.T) {
	for ua, want := range map[string]string{
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36":                             "Chrome on Windows",
		"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1": "Safari on iPhone",
		"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36 EdgA/131.0 Edg/131.0":           "Edge on Android",
		"": "Unknown device",
	} {
		if got := DeviceLabel(ua); got != want {
			t.Errorf("%q: %q, want %q", ua, got, want)
		}
	}
}

// A signed-out device's token stops working; other devices keep theirs.
func TestSignedOutDeviceIsRefused(t *testing.T) {
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
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	var userID string
	if err := pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES ('devices-' || gen_random_uuid() || '@example.com') RETURNING id::text`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	iss := NewIssuer("test-secret", 0)
	iss.Sessions = &Sessions{Pool: pool}
	req := httptest.NewRequest("POST", "/auth/otp/verify", nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0 Safari/537.36")
	req.Header.Set("X-Forwarded-For", "203.0.113.7, 10.0.0.1")
	phone, _ := iss.Sessions.start(req, userID)
	laptop, _ := iss.Sessions.start(req, userID)
	if !iss.Sessions.Active(ctx, phone, userID) || iss.Sessions.Active(ctx, phone, "00000000-0000-0000-0000-000000000000") {
		t.Fatal("active check")
	}

	// Sign the phone out from the laptop.
	del := httptest.NewRequest("DELETE", "/auth/sessions/"+phone, nil)
	del.SetPathValue("id", phone)
	del = del.WithContext(WithClaims(ctx, &Claims{Sid: laptop, RegisteredClaims: jwt.RegisteredClaims{Subject: userID}}))
	rec := httptest.NewRecorder()
	iss.Sessions.SignOutDevice(rec, del)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("sign out: %d %s", rec.Code, rec.Body)
	}
	if iss.Sessions.Active(ctx, phone, userID) || !iss.Sessions.Active(ctx, laptop, userID) {
		t.Fatal("phone should be out, laptop in")
	}
}
