package db

import (
	"context"
	"errors"
	"os"
	"strconv"

	"github.com/jackc/pgx/v5"
)

// MAX_ORGS caps how many businesses this Friday holds (unset or 0: no
// cap). Friday Host sets 1 on a customer's own server so it stays that
// business's Friday and can't be resold as a shared one; only Friday
// Host's shared Friday takes sign-ups for many businesses.
var ErrOrgCap = errors.New("this Friday is for one business only; another business can sign up at fridayhost.dev")

func MaxOrgs() int {
	n, _ := strconv.Atoi(os.Getenv("MAX_ORGS"))
	return max(n, 0)
}

type rowQuerier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// CheckOrgCap returns ErrOrgCap when one more business would pass MAX_ORGS.
// Inside a transaction it also takes a lock, so two sign-ups at once
// can't both slip under the cap.
func CheckOrgCap(ctx context.Context, q rowQuerier) error {
	limit := MaxOrgs()
	if limit == 0 {
		return nil
	}
	if _, inTx := q.(pgx.Tx); inTx {
		var ok bool
		// Any fixed key: only org creation takes it.
		if err := q.QueryRow(ctx, `SELECT pg_advisory_xact_lock(7731001) IS NOT NULL`).Scan(&ok); err != nil {
			return err
		}
	}
	var n int
	if err := q.QueryRow(ctx, `SELECT count(*) FROM core.orgs`).Scan(&n); err != nil {
		return err
	}
	if n >= limit {
		return ErrOrgCap
	}
	return nil
}
