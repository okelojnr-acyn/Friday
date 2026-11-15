package guss

import (
	"testing"

	"github.com/golang-jwt/jwt/v5"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

func TestParseServiceKey(t *testing.T) {
	org := "7adf296c-2b09-4c1e-9a3b-0123456789ab"
	secret := "0123456789abcdef0123456789abcdef0123456789abcdef"
	gotOrg, gotSecret, ok := parseServiceKey("fgs_" + org + "_" + secret)
	if !ok || gotOrg != org || gotSecret != secret {
		t.Fatalf("parse: %q %q %v", gotOrg, gotSecret, ok)
	}
	for _, bad := range []string{
		"", "fgs_", org + "_" + secret, "fgs_" + org, "fgs_short_" + secret, "fgs_" + org + "_tooshort",
	} {
		if _, _, ok := parseServiceKey(bad); ok {
			t.Errorf("accepted %q", bad)
		}
	}
}

func TestValidAccess(t *testing.T) {
	installed := []string{"inventory", "invoicing"}
	if err := ValidAccess(map[string]string{"inventory": "write", "invoicing": "none"}, installed); err != nil {
		t.Errorf("valid matrix refused: %v", err)
	}
	if err := ValidAccess(map[string]string{"inventory": "admin"}, installed); err == nil {
		t.Error("unknown level accepted")
	}
	if err := ValidAccess(map[string]string{"accounting": "read"}, installed); err == nil {
		t.Error("app that isn't installed accepted")
	}
}

func TestGussRoleFollowsFridayChainOfCommand(t *testing.T) {
	for friday, want := range map[string]string{
		"owner": "owner", "admin": "manager", "member": "staff", "viewer": "", "": "",
	} {
		if got := GussRole(friday); got != want {
			t.Errorf("GussRole(%q) = %q, want %q", friday, got, want)
		}
	}
}

func TestActorCarriesTheFridayPersonAndRole(t *testing.T) {
	a := actor(&auth.Claims{Role: "admin", Email: "joe@shop.test", RegisteredClaims: jwt.RegisteredClaims{Subject: "u9"}})
	if a["id"] != "friday:u9" || a["name"] != "joe@shop.test" || a["role"] != "manager" {
		t.Fatalf("actor = %v", a)
	}
}
