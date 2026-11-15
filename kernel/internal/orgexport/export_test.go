package orgexport

import "testing"

func TestSecretTablesNeverLeave(t *testing.T) {
	for _, tbl := range []string{"integration_credentials", "guss_service", "guss_link_codes", "webauthn_credentials", "otp_codes"} {
		if Included("core", tbl) {
			t.Errorf("core.%s must not be exported", tbl)
		}
	}
	for _, st := range [][2]string{{"core", "memberships"}, {"inventory", "products"}, {"crm", "contacts"}, {"core", "guss_links"}} {
		if !Included(st[0], st[1]) {
			t.Errorf("%s.%s must be exported", st[0], st[1])
		}
	}
	if Included("pg_catalog", "anything") || Included("information_schema", "columns") {
		t.Error("system schemas must not be exported")
	}
}

func TestQuoteIdent(t *testing.T) {
	if got := quoteIdent(`a"b`); got != `"a""b"` {
		t.Fatalf("got %s", got)
	}
}
