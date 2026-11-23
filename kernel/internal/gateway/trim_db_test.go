package gateway

import (
	"context"
	"testing"
)

// Short-lived rows are cleared once old; fresh ones stay.
func TestTrimExpiredClearsOnlyOldShortLivedRows(t *testing.T) {
	pool := eventsPool(t)
	ctx := context.Background()
	if _, err := pool.Exec(ctx, `DELETE FROM core.otp_codes WHERE email LIKE 'trim-%'`); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO core.otp_codes (email, purpose, code_hash, expires_at) VALUES
		('trim-old@x', 'login', 'h', now() - interval '8 days'),
		('trim-new@x', 'login', 'h', now() + interval '10 minutes')`); err != nil {
		t.Fatal(err)
	}
	TrimExpired(ctx, pool)
	var left []string
	rows, err := pool.Query(ctx, `SELECT email FROM core.otp_codes WHERE email LIKE 'trim-%'`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var e string
		rows.Scan(&e)
		left = append(left, e)
	}
	rows.Close()
	if len(left) != 1 || left[0] != "trim-new@x" {
		t.Fatalf("left: %v", left)
	}
}
