// Friday kernel: auth, orgs, the apps catalog, and the API gateway that
// every app service sits behind. See ARCHITECTURE.md for the full picture.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/gateway"
	"github.com/acyn-innovation/friday/kernel/internal/integrations"
	"github.com/acyn-innovation/friday/kernel/internal/mail"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

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
	kernelPublicURL := envOr("KERNEL_PUBLIC_URL", "http://localhost:"+envOr("PORT", "8080"))
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

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"status":"ok","service":"kernel"}`))
	})

	// Passwordless throughout: a passkey ceremony or an emailed one-time
	// code, matching Acyn Wallet's auth model. See internal/auth/handlers.go.
	mux.HandleFunc("POST /auth/register", authHandlers.Register)
	mux.HandleFunc("POST /auth/otp/request", authHandlers.OtpRequest)
	mux.HandleFunc("POST /auth/otp/verify", authHandlers.OtpVerify)
	mux.HandleFunc("POST /auth/invites/accept", authHandlers.AcceptInvite)
	// POS clock-in device: logs in an existing account or joins an
	// admin-invited one, same honest-vs-silent tradeoff call noted on
	// PosRequestCode itself. Never reaches completeSignup -- see
	// PosVerifyCode's own doc comment for why.
	mux.HandleFunc("POST /auth/pos/code", authHandlers.PosRequestCode)
	mux.HandleFunc("POST /auth/pos/verify", authHandlers.PosVerifyCode)
	mux.HandleFunc("POST /auth/passkey/login-options", authHandlers.PasskeyLoginOptions)
	mux.HandleFunc("POST /auth/passkey/login-verify", authHandlers.PasskeyLoginVerify)
	mux.Handle("POST /auth/passkey/register-options", requireAuth(http.HandlerFunc(authHandlers.PasskeyRegisterOptions)))
	mux.Handle("POST /auth/passkey/register-verify", requireAuth(http.HandlerFunc(authHandlers.PasskeyRegisterVerify)))
	mux.Handle("GET /auth/me", requireAuth(http.HandlerFunc(authHandlers.Me)))
	mux.Handle("POST /orgs/invites", requireAuth(http.HandlerFunc(authHandlers.InviteMember)))

	mux.Handle("GET /orgs/apps", requireAuth(http.HandlerFunc(catalog.List)))
	mux.Handle("POST /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(true)))
	mux.Handle("DELETE /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(false)))

	members := &org.Members{Pool: pool}
	mux.Handle("GET /orgs/members", requireAuth(http.HandlerFunc(members.List)))
	mux.Handle("PATCH /orgs/members/{user_id}/role", requireAuth(http.HandlerFunc(members.SetRole)))
	mux.Handle("DELETE /orgs/members/{user_id}", requireAuth(http.HandlerFunc(members.Remove)))

	integrationHandlers := &integrations.Handlers{
		Pool:          pool,
		InternalToken: eventsToken,
		JWTSecret:     jwtSecret,
		PublicURL:     kernelPublicURL,
		CORSOrigin:    corsOrigin,
	}
	mux.Handle("GET /orgs/integrations", requireAuth(http.HandlerFunc(integrationHandlers.List)))
	mux.Handle("GET /orgs/integrations/{provider}", requireAuth(http.HandlerFunc(integrationHandlers.Get)))
	mux.Handle("PUT /orgs/integrations/{provider}", requireAuth(http.HandlerFunc(integrationHandlers.Set)))
	mux.Handle("DELETE /orgs/integrations/{provider}", requireAuth(http.HandlerFunc(integrationHandlers.Delete)))
	mux.HandleFunc("GET /internal/integrations/{org_id}/{provider}", integrationHandlers.GetInternal)
	mux.Handle("POST /orgs/integrations/google_calendar/oauth/start", requireAuth(http.HandlerFunc(integrationHandlers.GoogleOAuthStart)))
	// Not behind requireAuth -- Google's redirect back to this URL carries
	// no Authorization header; see google_oauth.go's oauthStateClaims doc.
	mux.HandleFunc("GET /orgs/integrations/google_calendar/oauth/callback", integrationHandlers.GoogleOAuthCallback)

	mux.HandleFunc("POST /internal/events", gateway.EventsHandler(apps, eventsToken))

	for _, app := range apps {
		proxy, err := gateway.NewAppProxy(app)
		if err != nil {
			log.Fatalf("configure proxy for %s: %v", app.Name, err)
		}
		mux.Handle("/api/"+app.Name+"/", requireAuth(proxy))
		log.Printf("routing /api/%s/* -> %s", app.Name, app.BaseURL)
	}

	handler := withCORS(corsOrigin, mux)

	log.Printf("kernel listening on %s", addr)
	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatal(err)
	}
}

// withCORS is the single owner of CORS for every route, the kernel's own
// and the proxied /api/{app}/* ones alike. Previously proxied routes
// relied on each app's own CORSMiddleware, configured from each app's
// own CORS_ORIGINS env -- found 2026-11-10: crm and invoicing still only
// allowed an old Vercel origin while the other six allowed the real one,
// so the browser silently dropped every crm/invoicing response ("Could
// not load the pipeline", empty invoice list) and every kernel-generated
// /api 401 (no CORS headers at all) surfaced as an opaque "Failed to
// fetch". gateway.NewAppProxy strips the app's own Access-Control-*
// headers, so setting them here never produces a doubled
// Access-Control-Allow-Origin (which browsers also reject).
func withCORS(origin string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
		w.Header().Add("Vary", "Origin")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
