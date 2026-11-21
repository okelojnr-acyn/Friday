package access

import (
	"bytes"
	"os"
	"strings"
	"testing"
)

func TestScopeFollowsRolesAndPermissions(t *testing.T) {
	cases := []struct {
		rule, role string
		perms      []string
		want       string
	}{
		{"pos.sell", "member", nil, ""},
		{"pos.sell", "member", []string{"cashier"}, "loc"},
		{"pos.sell", "team_leader", []string{"warehouse"}, ""},
		{"pos.sell", "branch_manager", nil, "loc"},
		{"pos.sell", "owner", nil, "all"},
		{"pos.sell", "viewer", nil, ""},
		{"sales.read", "member", nil, "own"},
		{"sales.read", "team_leader", nil, "team"},
		{"sales.read", "viewer", nil, "all"},
		{"stock.read", "member", []string{"warehouse"}, "loc"},
		{"stock.read", "member", []string{"logistics"}, ""},
		{"pay.read", "admin", nil, "all"}, // admins hold every permission
		{"pay.read", "branch_manager", nil, "own"},
		{"pay.write", "branch_manager", nil, ""},
		{"books.read", "viewer", nil, ""},
		{"books.read", "viewer", []string{"accounting"}, "all"},
		{"host.manage", "admin", nil, ""},
		{"no.such.rule", "owner", nil, ""},
	}
	for _, c := range cases {
		if got := Scope(c.rule, c.role, c.perms); got != c.want {
			t.Errorf("Scope(%s, %s, %v) = %q, want %q", c.rule, c.role, c.perms, got, c.want)
		}
	}
}

func TestRulesAreWellFormed(t *testing.T) {
	scopes := map[string]bool{"all": true, "loc": true, "team": true, "own": true}
	for rule, roles := range Rules {
		for role, spec := range roles {
			if !ValidRole(role) {
				t.Errorf("%s: unknown role %q", rule, role)
			}
			scope, need, has := strings.Cut(spec, "+")
			if !scopes[scope] {
				t.Errorf("%s/%s: unknown scope %q", rule, role, scope)
			}
			if has {
				for _, p := range strings.Split(need, "|") {
					if !ValidPerm(p) {
						t.Errorf("%s/%s: unknown permission %q", rule, role, p)
					}
				}
			}
			// Viewers only read; the gateway refuses their writes anyway.
			if role == "viewer" && !strings.HasSuffix(rule, ".read") {
				t.Errorf("%s: a viewer rule that isn't a read", rule)
			}
		}
	}
	if Rank("owner") <= Rank("admin") || Rank("admin") <= Rank("branch_manager") ||
		Rank("branch_manager") <= Rank("team_leader") || Rank("team_leader") <= Rank("member") ||
		Rank("member") <= Rank("viewer") || Rank("nobody") != -1 {
		t.Error("the role ladder is out of order")
	}
}

// The Python apps read the same rules; they must never drift apart.
func TestPythonAppsHaveTheSameRules(t *testing.T) {
	py, err := os.ReadFile("../../../packages/py-common/friday_common/access_rules.json")
	if err != nil {
		t.Fatal(err)
	}
	norm := func(b []byte) []byte { return bytes.ReplaceAll(b, []byte("\r\n"), []byte("\n")) }
	if !bytes.Equal(norm(py), norm(RulesJSON)) {
		t.Fatal("kernel/internal/access/rules.json and packages/py-common/friday_common/access_rules.json differ: copy one over the other")
	}
}
