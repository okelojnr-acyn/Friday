package auth

import (
	"context"
	"slices"
	"testing"
	"time"
)

// A manager signing in at the till with a PIN is a member there but keeps
// the cashier job, once; their own jobs stay (owner, 2026-11-22).
func TestIssueViaAddsPermsOnce(t *testing.T) {
	iss := NewIssuer("secret", time.Hour)
	iss.Scope = func(context.Context, string, string, string) ([]string, []string, []string, error) {
		return []string{"warehouse", "cashier"}, []string{"*"}, nil, nil
	}
	tok, err := iss.IssueVia("u1", "o1", "member", "m@x", PosVia, posAccess, time.Minute, "cashier", "sales")
	if err != nil {
		t.Fatal(err)
	}
	c, err := iss.Verify(tok)
	if err != nil {
		t.Fatal(err)
	}
	if c.Role != "member" || !slices.Equal(c.Perms, []string{"warehouse", "cashier", "sales"}) {
		t.Fatalf("role %q perms %v", c.Role, c.Perms)
	}
}
