// Package svcauth checks the shared token Friday's own services use to
// call each other (KERNEL_EVENTS_TOKEN).
package svcauth

import (
	"crypto/subtle"
	"net/http"
	"net/url"
	"os"
)

// DevSecret is the built-in value for development; never valid elsewhere.
const DevSecret = "dev-only-change-me"

// Bearer reports whether r carries "Bearer <token>". An empty token never
// matches, and the comparison takes the same time whatever the guess.
func Bearer(r *http.Request, token string) bool {
	return token != "" &&
		subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) == 1
}

// Weak names the given secrets (name -> value) that are empty or the
// development value, unless this is development: FRIDAY_DEV=1, or the
// database is on this machine.
func Weak(databaseURL string, secrets map[string]string) []string {
	if os.Getenv("FRIDAY_DEV") == "1" {
		return nil
	}
	if u, err := url.Parse(databaseURL); err == nil {
		switch u.Hostname() {
		case "localhost", "127.0.0.1", "::1":
			return nil
		}
	}
	var weak []string
	for name, v := range secrets {
		if v == "" || v == DevSecret {
			weak = append(weak, name)
		}
	}
	return weak
}
