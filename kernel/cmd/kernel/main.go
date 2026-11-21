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

	"github.com/acyn-innovation/friday/kernel/internal/access"
	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/gateway"
	"github.com/acyn-innovation/friday/kernel/internal/guss"
	"github.com/acyn-innovation/friday/kernel/internal/importsource"
	"github.com/acyn-innovation/friday/kernel/internal/integrations"
	"github.com/acyn-innovation/friday/kernel/internal/mail"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/orgexport"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	if len(os.Args) > 2 && os.Args[1] == "export" {
		// kernel export <org id> > export.zip
		ctx := context.Background()
		pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
		if err != nil {
			log.Fatalf("db connect: %v", err)
		}
		if err := orgexport.Write(ctx, pool, os.Args[2], os.Getenv("FRIDAY_VERSION"), os.Stdout); err != nil {
			log.Fatal(err)
		}
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "dbcheck" {
		os.Exit(runDBCheck())
	}
	if len(os.Args) > 1 && os.Args[1] == "bootstrap" {
		if err := runBootstrap(os.Args[2:]); err != nil {
			log.Fatal(err)
		}
		return
	}
	// The image's ENTRYPOINT is ./kernel, so `docker compose run kernel
	// ./kernel dbcheck` arrives here as ["./kernel", "dbcheck"]. Starting the
	// server on arguments it doesn't know hung CI for 20 minutes
	// (2026-11-15); say what's wrong instead.
	if len(os.Args) > 1 {
		log.Fatalf("unknown command %q; commands: bootstrap, export, dbcheck (no arguments starts the server)", strings.Join(os.Args[1:], " "))
	}
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
	issuer.Scope = func(ctx context.Context, userID, orgID, role string) ([]string, []string, []string, error) {
		return access.Load(ctx, pool, orgID, userID, role)
	}
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
	// Cashier PIN (plan section 11): trusted tills, PINs, lockout.
	mux.HandleFunc("GET /auth/pos/cashiers", authHandlers.PosCashiers)
	mux.HandleFunc("POST /auth/pos/pin", authHandlers.PosPinLogin)
	mux.Handle("POST /pos/devices", requireAuth(http.HandlerFunc(authHandlers.EnrolPosDevice)))
	mux.Handle("GET /pos/devices", requireAuth(http.HandlerFunc(authHandlers.ListPosDevices)))
	mux.Handle("DELETE /pos/devices/{id}", requireAuth(http.HandlerFunc(authHandlers.RevokePosDevice)))
	mux.Handle("GET /pos/pin", requireAuth(http.HandlerFunc(authHandlers.MyPosPin)))
	mux.Handle("PUT /pos/pin", requireAuth(http.HandlerFunc(authHandlers.SetPosPin)))
	mux.Handle("GET /pos/pins", requireAuth(http.HandlerFunc(authHandlers.ListPosPins)))
	mux.Handle("PUT /pos/pins/{user_id}", requireAuth(http.HandlerFunc(authHandlers.SetPosPin)))
	mux.Handle("POST /pos/pins/{user_id}/unlock", requireAuth(http.HandlerFunc(authHandlers.UnlockPosPin)))
	mux.Handle("DELETE /pos/pins/{user_id}", requireAuth(http.HandlerFunc(authHandlers.ClearPosPin)))
	mux.Handle("GET /pos/pin-events", requireAuth(http.HandlerFunc(authHandlers.PosPinEvents)))
	mux.Handle("POST /orgs/invites", requireAuth(http.HandlerFunc(authHandlers.InviteMember)))

	orgSettings := &org.Settings{Pool: pool}
	mux.Handle("GET /orgs/settings", requireAuth(http.HandlerFunc(orgSettings.Get)))
	mux.Handle("PUT /orgs/settings", requireAuth(http.HandlerFunc(orgSettings.Put)))
	orgEtims := &org.Etims{Pool: pool, InternalToken: eventsToken, Automation: os.Getenv("ETIMS_AUTOMATION") == "1"}
	mux.Handle("GET /orgs/etims", requireAuth(http.HandlerFunc(orgEtims.Get)))
	mux.Handle("PUT /orgs/etims", requireAuth(http.HandlerFunc(orgEtims.Put)))
	mux.HandleFunc("GET /internal/etims/{org_id}", orgEtims.GetInternal)
	mux.Handle("GET /orgs/apps", requireAuth(http.HandlerFunc(catalog.List)))
	mux.Handle("POST /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(true)))
	mux.Handle("DELETE /orgs/apps/{app}/install", requireAuth(catalog.SetInstalled(false)))

	members := &org.Members{Pool: pool}
	mux.Handle("GET /orgs/members", requireAuth(http.HandlerFunc(members.List)))
	mux.Handle("PATCH /orgs/members/{user_id}/role", requireAuth(http.HandlerFunc(members.SetRole)))
	mux.Handle("DELETE /orgs/members/{user_id}", requireAuth(http.HandlerFunc(members.Remove)))
	people := &org.People{Pool: pool}
	mux.Handle("PATCH /orgs/members/{user_id}", requireAuth(http.HandlerFunc(people.UpdatePerson)))
	mux.Handle("GET /orgs/me/permissions", requireAuth(http.HandlerFunc(people.MyPermissions)))
	mux.Handle("GET /orgs/locations", requireAuth(http.HandlerFunc(people.Locations)))
	mux.Handle("POST /orgs/locations", requireAuth(http.HandlerFunc(people.SaveLocation)))
	mux.Handle("PATCH /orgs/locations/{id}", requireAuth(http.HandlerFunc(people.SaveLocation)))

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

	gussHandlers := &guss.Handlers{Pool: pool, Issuer: issuer}
	mux.Handle("GET /guss/status", requireAuth(http.HandlerFunc(gussHandlers.Status)))
	mux.Handle("GET /guss/access", requireAuth(http.HandlerFunc(gussHandlers.Access)))
	mux.Handle("PUT /guss/access", requireAuth(http.HandlerFunc(gussHandlers.SetAccess)))
	mux.Handle("POST /guss/service-key", requireAuth(http.HandlerFunc(gussHandlers.NewServiceKey)))
	mux.Handle("POST /guss/link", requireAuth(http.HandlerFunc(gussHandlers.Link)))
	mux.Handle("DELETE /guss/links/{telegram_id}", requireAuth(http.HandlerFunc(gussHandlers.Unlink)))
	// Called by Guss itself with its service key (not a user session).
	mux.HandleFunc("POST /guss/svc/link-code", gussHandlers.LinkCode)
	mux.HandleFunc("POST /guss/svc/token", gussHandlers.Token)
	mux.HandleFunc("GET /guss/svc/people", gussHandlers.People)
	mux.Handle("POST /guss/chat", requireAuth(http.HandlerFunc(gussHandlers.Chat)))
	mux.Handle("GET /guss/report", requireAuth(http.HandlerFunc(gussHandlers.Report)))
	mux.Handle("GET /guss/voids", requireAuth(http.HandlerFunc(gussHandlers.Voids)))
	mux.Handle("POST /admin/orgs/{id}/export", requireAuth(orgexport.Handler(pool, os.Getenv("FRIDAY_VERSION"),
		func(r *http.Request) (string, string, string, bool) {
			c, ok := auth.FromContext(r.Context())
			if !ok {
				return "", "", "", false
			}
			return c.OrgID, c.Role, c.Via, true
		})))
	// Plan 2.4: read a customer's old database for the import screen.
	mux.Handle("POST /orgs/import/source", requireAuth(&importsource.Handler{
		AllowPrivate: os.Getenv("FRIDAY_IMPORT_ALLOW_PRIVATE") == "true",
		Claims: func(r *http.Request) (string, string, bool) {
			c, ok := auth.FromContext(r.Context())
			if !ok {
				return "", "", false
			}
			return c.Role, c.Via, true
		},
	}))
	mux.Handle("POST /guss/voids/{number}", requireAuth(http.HandlerFunc(gussHandlers.DecideVoid)))

	mux.HandleFunc("POST /internal/events", gateway.EventsHandler(pool, eventsToken))
	// Sends queued events to subscribers, retrying until each accepts.
	go (&gateway.Deliverer{Pool: pool, Apps: apps, Token: eventsToken}).Run(ctx)
	gateway.WithEventCounts(gateway.EventCounts(pool))
	mux.Handle("GET /health", gateway.HealthHandler(apps, pool, nil))

	for _, app := range apps {
		proxy, err := gateway.NewAppProxy(app)
		if err != nil {
			log.Fatalf("configure proxy for %s: %v", app.Name, err)
		}
		mux.Handle("/api/"+app.Name+"/", requireAuth(gateway.EnforceAccess(app.Name, proxy)))
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
		w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Pos-Device")
		w.Header().Add("Vary", "Origin")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
