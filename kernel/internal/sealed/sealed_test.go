package sealed

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
)

func key(b byte) string { return base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{b}, 32)) }

func TestSealOpenAndPlainRowsStillRead(t *testing.T) {
	box, err := New(key(1))
	if err != nil {
		t.Fatal(err)
	}
	plain := []byte(`{"secret_key":"sk_live_abcd1234"}`)
	stored, err := box.Seal(plain)
	if err != nil || bytes.Contains(stored, []byte("sk_live")) || !IsSealed(stored) {
		t.Fatalf("sealed %s %v", stored, err)
	}
	if got, err := box.Open(stored); err != nil || !bytes.Equal(got, plain) {
		t.Fatalf("open: %s %v", got, err)
	}
	if got, _ := box.Open(plain); !bytes.Equal(got, plain) {
		t.Fatal("a row from before the key reads as it is")
	}
	other, _ := New(key(2))
	if _, err := other.Open(stored); err == nil {
		t.Fatal("a different key must not open it")
	}
	var none *Box
	if _, err := none.Open(stored); err == nil {
		t.Fatal("no key can't open a sealed row")
	}
	if got, _ := none.Seal(plain); !bytes.Equal(got, plain) {
		t.Fatal("no key: stored plain, as before")
	}
	if _, err := New("short"); err == nil {
		t.Fatal("bad key accepted")
	}
}

func TestMaskedAndMerge(t *testing.T) {
	stored := map[string]any{"secret_key": "sk_live_abcd1234", "receipt_email": "a@b.co", "client_id": "id-1"}
	m := Masked(stored)
	if m["secret_key"] != Mask+"1234" || m["receipt_email"] != "a@b.co" || m["client_id"] != "id-1" {
		t.Fatalf("masked: %v", m)
	}
	back := Merge(map[string]any{"secret_key": m["secret_key"], "receipt_email": "new@b.co"}, stored)
	if back["secret_key"] != "sk_live_abcd1234" || back["receipt_email"] != "new@b.co" {
		t.Fatalf("merge kept: %v", back)
	}
	changed := Merge(map[string]any{"secret_key": "sk_live_new"}, stored)
	if changed["secret_key"] != "sk_live_new" {
		t.Fatal("a new key replaces the old")
	}
	for _, f := range []string{"secret_key", "webhook_secret", "token", "api_key", "client_secret", "private_key", "refresh_token"} {
		if !IsSecret(f) {
			t.Fatalf("%s should be secret", f)
		}
	}
	if IsSecret("publishable_key") || IsSecret("client_id") || IsSecret("url") || strings.Contains(Mask, "x") {
		t.Fatal("not secrets")
	}
}
