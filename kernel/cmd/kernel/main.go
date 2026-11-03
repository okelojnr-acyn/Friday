// Friday kernel: auth, orgs, the apps catalog, and the API gateway that
// every app service sits behind. See ARCHITECTURE.md for the full picture.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/gateway"
	"github.com/acyn-innovation/friday/kernel/internal/integrations"
	"github.com/acyn-innovation/friday/kernel/internal/mail"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/ratelimit"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// maxRequestBodyBytes caps every request body the kernel itself reads
// (auth payloads, integration config, catalog toggles -- all genuinely
// small). Deliberately generous enough to never matter for real traffic
// while still bounding a maliciously huge body: 1 MiB.
const maxRequestBodyBytes = 1 << 20

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	ctx := context.Background()

	databaseURL := envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday")
	jwtSecret := envOr("JWT_SECRET", "dev-only-change-me")
	eventsToken := envOr("KERNEL_EVENTS_TOKEN", "dev-only-change-me")
	addr := ":" + envOr("PORT", "8080")
	migrationsDir := envOr("MIGRATIONS_DIR", "kernel/migrations")
	corsOrigin := envOr("CORS_ORIGIN", "http://localhost:5173")
	webauthnRPID := envOr("WEBAUTHN_RP_ID", "localhost")
	webauthnRPName := envOr("WEBAUTHN_RP_NAME", "Friday")

	pool, err := db.Connect(ctx, databaseURL)
	if err != nil {
		log.Fatalf("db connect: %v", err)
	}
	defer pool.Close()

	if err := db.Migrate(ctx, pool, migrationsDir); err != nil {
		log.Fatalf("migrate: %v", err)
	}

	apps := registry.Load()
	catalog := &org.Catalog{Pool: pool, Apps: apps}
	if err := catalog.SeedApps(ctx); err != nil {
		log.Fatalf("seed apps: %v", err)
	}

	// Two tiers: a tight quota on auth-sensitive routes specifically
	// (brute-forcing an OTP or spamming a login attempt is the thing
	// that actually matters to stop hard), and a looser one across
	// everything the kernel serves itself as basic abuse/DoS protection.
	// Neither covers /api/{app}/* -- each app service is free to set
	// its own limits appropriate to its own workload (e.g. a bulk
	// import legitimately posts more often than a login attempt should).
	authLimiter := ratelimit.New(10, time.Minute)
	generalLimiter := ratelimit.New(120, time.Minute)

	issuer := auth.NewIssuer(jwtSecret, 24*time.Hour)
	webAuthn, err := auth.NewWebAuthn(webauthnRPID, webauthnRPName, []string{corsOrigin})
	if err != nil {
		log.Fatalf("configure webauthn: %v", err)
	}
	authHandlers := &auth.Handlers{
		Pool:     pool,
		Issuer:   issuer,
		WebAuthn: webAuthn,
		Mailer:   mail.New(),
		Otp:      &auth.OtpStore{Pool: pool},
	}
	requireAuth := auth.RequireAuth(issuer)

	mux := http.NewServeMux()

	// withBody+authLimited: every auth POST goes through both a tight
	// per-IP quota and the request-body size cap -- these bodies are
	// always tiny (an email, a code, a WebAuthn response), so there's
	// no legitimate reason for a huge one.
	authLimited := func(h http.HandlerFunc) http.Handler {
		return authLimiter.Middleware("auth", withMaxBodySize(http.HandlerFunc(h)))
	}

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"status":"ok","service":"kernel"}`))
	})

	// Passwordless throughout: a passkey ceremony or an emailed one-time
	// code, matching Acyn Wallet's auth model. See internal/auth/handlers.go.
	mux.Handle("POST /auth/register", authLimited(authHandlers.Register))
	mux.Handle("POST /auth/otp/request", authLimited(authHandlers.OtpRequest))
	mux.Handle("POST /auth/otp/verify", authLimited(authHandlers.OtpVerify))
	mux.Handle("POST /auth/passkey/login-options", authLimited(authHandlers.PasskeyLoginOptions))
	mux.Handle("POST /auth/passkey/login-verify", authLimited(authHandlers.PasskeyLoginVerify))
	mux.Handle("POST /auth/passkey/register-options",
		authLimiter.Middleware("auth", requireAuth(http.HandlerFunc(authHandlers.PasskeyRegisterOptions))))
	mux.Handle("POST /auth/passkey/register-verify",
		authLimiter.Middleware("auth", withMaxBodySize(requireAuth(http.HandlerFunc(authHandlers.PasskeyRegisterVerify)))))
	mux.Handle("GET /auth/me", requireAuth(http.HandlerFunc(authHandlers.Me)))

	mux.Handle("GET /orgs/apps", requireAuth(http.HandlerFunc(catalog.List)))
	mux.Handle("POST /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(true)))
	mux.Handle("DELETE /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(false)))

	integrationHandlers := &integrations.Handlers{Pool: pool, InternalToken: eventsToken}
	mux.Handle("GET /orgs/integrations", requireAuth(http.HandlerFunc(integrationHandlers.List)))
	mux.Handle("GET /orgs/integrations/{provider}", requireAuth(http.HandlerFunc(integrationHandlers.Get)))
	mux.Handle("PUT /orgs/integrations/{provider}", withMaxBodySize(requireAuth(http.HandlerFunc(integrationHandlers.Set))))
	mux.Handle("DELETE /orgs/integrations/{provider}", requireAuth(http.HandlerFunc(integrationHandlers.Delete)))
	mux.HandleFunc("GET /internal/integrations/{org_id}/{provider}", integrationHandlers.GetInternal)

	mux.HandleFunc("POST /internal/events", gateway.EventsHandler(apps, eventsToken))

	for _, app := range apps {
		proxy, err := gateway.NewAppProxy(app)
		if err != nil {
			log.Fatalf("configure proxy for %s: %v", app.Name, err)
		}
		mux.Handle("/api/"+app.Name+"/", requireAuth(proxy))
		log.Printf("routing /api/%s/* -> %s", app.Name, app.BaseURL)
	}

	// Outermost to innermost: CORS first (so a preflight OPTIONS short-
	// circuits before spending a rate-limit token or growing a header
	// set it'll never see past), then security headers on every
	// response, then the general per-IP quota across everything the
	// kernel serves -- /api/{app}/* included, since a proxied request
	// still arrived at this process and is worth bounding too, even
	// though its own tighter auth-specific limiting lives on the
	// individual routes above instead.
	handler := withCORS(corsOrigin, withSecurityHeaders(generalLimiter.Middleware("general", mux)))

	log.Printf("kernel listening on %s", addr)
	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatal(err)
	}
}

// withMaxBodySize caps a request body the kernel itself will read
// (every kernel-served route's payload is small -- an email, a code, a
// WebAuthn response, a provider config blob). Not applied to the
// /api/{app}/* proxy -- each app service sets its own limits
// appropriate to its own workload (e.g. a bulk import).
func withMaxBodySize(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyBytes)
		next.ServeHTTP(w, r)
	})
}

// withSecurityHeaders sets the handful of response headers that cost
// nothing and close off a real (if narrow) class of browser-side
// attacks: MIME-sniffing a response into executing as something it
// isn't, framing the app in a clickjacking overlay, and leaking the
// full referrer URL (which can carry a session-bearing path) to a
// third-party site a link points to.
func withSecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "same-origin")
		next.ServeHTTP(w, r)
	})
}

// withCORS handles preflight for every route (proxied routes are
// auth-gated, so an OPTIONS preflight -- which never carries the
// Authorization header -- would otherwise 401 before reaching the app).
// For the actual request, it only sets CORS headers on routes the kernel
// serves itself. /api/{app}/* responses already carry CORS headers from
// the app's own CORSMiddleware (friday_common.create_app) -- the proxy
// forwards the Origin header through, so the app sees it and responds
// accordingly -- and httputil.ReverseProxy copies backend headers with
// Add, not Set, so setting them here too would duplicate the header.
// Browsers reject a doubled Access-Control-Allow-Origin as invalid CORS,
// which fails every proxied request with an opaque "Failed to fetch".
func withCORS(origin string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if !strings.HasPrefix(r.URL.Path, "/api/") {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
		}
		next.ServeHTTP(w, r)
	})
}
