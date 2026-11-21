// Package access is who sees what in Friday (plan section 12): the role
// ladder, the permissions a person can hold, and the rules table every
// app follows (rules.json, the same file the Python apps read as
// friday_common/access_rules.json).
package access

import (
	"context"
	_ "embed"
	"encoding/json"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed rules.json
var RulesJSON []byte

// Rules is rule -> role -> scope ("all", "loc+cashier", ...).
var Rules = func() map[string]map[string]string {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(RulesJSON, &raw); err != nil {
		panic("access: rules.json: " + err.Error())
	}
	out := map[string]map[string]string{}
	for k, v := range raw {
		if strings.HasPrefix(k, "_") {
			continue
		}
		var m map[string]string
		if err := json.Unmarshal(v, &m); err != nil {
			panic("access: rules.json " + k + ": " + err.Error())
		}
		out[k] = m
	}
	return out
}()

// Roles, highest first. "member" is shown as "Staff".
var Roles = []string{"owner", "admin", "branch_manager", "team_leader", "member", "viewer"}

// Perms a person can hold (owners and admins hold them all).
var Perms = []string{"cashier", "warehouse", "logistics", "purchasing", "sales", "accounting", "hr"}

// Rank orders roles; -1 for an unknown one.
func Rank(role string) int {
	if i := slices.Index(Roles, role); i >= 0 {
		return len(Roles) - 1 - i
	}
	return -1
}

func ValidRole(role string) bool { return Rank(role) >= 0 }

func ValidPerm(p string) bool { return slices.Contains(Perms, p) }

// Scope is what `role` with `perms` may do under `rule`: "all", "loc",
// "team" or "own", or "" for nothing.
func Scope(rule, role string, perms []string) string {
	spec := Rules[rule][role]
	if spec == "" {
		return ""
	}
	scope, need, found := strings.Cut(spec, "+")
	if !found {
		return scope
	}
	if role == "owner" || role == "admin" {
		return scope
	}
	for _, p := range strings.Split(need, "|") {
		if slices.Contains(perms, p) {
			return scope
		}
	}
	return ""
}

// All is every rule's scope for a person, for the web to show only what
// they can use.
func All(role string, perms []string) map[string]string {
	out := map[string]string{}
	for rule := range Rules {
		if s := Scope(rule, role, perms); s != "" {
			out[rule] = s
		}
	}
	return out
}

// maxTeam caps the team carried in a token (a header has to stay small).
// A leader with more than maxTeam people under them gets TeamByLocation
// instead of the list, and apps read their "team" scope as "loc".
const maxTeam = 100

// TeamByLocation stands in for a team too big to list in a token.
const TeamByLocation = "*loc"

// Load is what a token carries for a person: their permissions (all for
// owners and admins), their locations ("*" for all: owners, admins,
// viewers, and anyone with none listed) and their team (everyone who
// reports to them, directly or further down, up to maxTeam).
func Load(ctx context.Context, pool *pgxpool.Pool, orgID, userID, role string) (perms, locs, team []string, err error) {
	if role == "owner" || role == "admin" {
		perms = slices.Clone(Perms)
	} else if err = pool.QueryRow(ctx,
		`SELECT perms FROM core.memberships WHERE org_id = $1 AND user_id::text = $2`, orgID, userID,
	).Scan(&perms); err != nil {
		return nil, nil, nil, err
	}
	locs = []string{"*"}
	if role != "owner" && role != "admin" && role != "viewer" {
		rows, err := pool.Query(ctx,
			`SELECT location_id::text FROM core.membership_locations WHERE org_id = $1 AND user_id::text = $2 ORDER BY 1`,
			orgID, userID)
		if err != nil {
			return nil, nil, nil, err
		}
		var mine []string
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return nil, nil, nil, err
			}
			mine = append(mine, id)
		}
		rows.Close()
		if len(mine) > 0 {
			locs = mine
		}
	}
	if role == "branch_manager" || role == "team_leader" {
		rows, err := pool.Query(ctx, `
			WITH RECURSIVE t(user_id, depth) AS (
				SELECT user_id, 1 FROM core.memberships WHERE org_id = $1 AND reports_to::text = $2
				UNION
				SELECT m.user_id, t.depth + 1 FROM core.memberships m JOIN t ON m.reports_to = t.user_id
				WHERE m.org_id = $1 AND t.depth < 10
			)
			SELECT DISTINCT user_id::text FROM t WHERE user_id::text <> $2 LIMIT $3`, orgID, userID, maxTeam+1)
		if err != nil {
			return nil, nil, nil, err
		}
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return nil, nil, nil, err
			}
			team = append(team, id)
		}
		rows.Close()
		if len(team) > maxTeam {
			team = []string{TeamByLocation}
		}
	}
	if perms == nil {
		perms = []string{}
	}
	return perms, locs, team, nil
}
