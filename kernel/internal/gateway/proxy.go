// Package gateway is the single entry point web/ talks to. It reverse-proxies
// /api/{app}/* to the right app service and fans out domain events between
// apps. Apps never call each other directly -- every cross-app interaction
// goes through here, which is what lets any single app be redeployed,
// rewritten, or replaced without the others noticing.
package gateway

import (
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// NewAppProxy returns a handler that strips the "/api/{app}" prefix and
// forwards everything else to that app's base URL, passing the caller's
// bearer token through unchanged so the app can verify it itself.
func NewAppProxy(app registry.App) (http.Handler, error) {
	target, err := url.Parse(app.BaseURL)
	if err != nil {
		return nil, err
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	prefix := "/api/" + app.Name

	originalDirector := proxy.Director
	proxy.Director = func(r *http.Request) {
		r.URL.Path = trimPrefix(r.URL.Path, prefix)
		originalDirector(r)
	}
	// The kernel's withCORS owns CORS for every route; drop whatever the
	// app sent so the browser never sees a doubled or stale-origin header.
	proxy.ModifyResponse = stripCORS
	return proxy, nil
}

func stripCORS(resp *http.Response) error {
	for k := range resp.Header {
		if strings.HasPrefix(http.CanonicalHeaderKey(k), "Access-Control-") {
			resp.Header.Del(k)
		}
	}
	return nil
}

func trimPrefix(path, prefix string) string {
	if len(path) >= len(prefix) && path[:len(prefix)] == prefix {
		rest := path[len(prefix):]
		if rest == "" {
			return "/"
		}
		return rest
	}
	return path
}
