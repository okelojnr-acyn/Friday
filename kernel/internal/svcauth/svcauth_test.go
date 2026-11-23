package svcauth

import (
	"net/http/httptest"
	"testing"
)

func TestBearerNeverMatchesAnEmptyToken(t *testing.T) {
	r := httptest.NewRequest("GET", "/internal/x", nil)
	r.Header.Set("Authorization", "Bearer ")
	if Bearer(r, "") {
		t.Fatal("empty token matched")
	}
	r.Header.Set("Authorization", "Bearer s3cret")
	if !Bearer(r, "s3cret") || Bearer(r, "other") {
		t.Fatal("wrong match")
	}
}

func TestDevSecretsOnlyInDevelopment(t *testing.T) {
	t.Setenv("FRIDAY_DEV", "")
	secrets := map[string]string{"JWT_SECRET": DevSecret}
	if got := Weak("postgres://u:p@pgbouncer:6432/db", secrets); len(got) != 1 {
		t.Fatalf("production with the dev secret: %v", got)
	}
	if got := Weak("postgres://u:p@localhost:5432/db", secrets); got != nil {
		t.Fatalf("local database: %v", got)
	}
	t.Setenv("FRIDAY_DEV", "1")
	if got := Weak("postgres://u:p@pgbouncer:6432/db", secrets); got != nil {
		t.Fatalf("FRIDAY_DEV=1: %v", got)
	}
}
