// Friday kernel: auth, orgs, the apps catalog, and the API gateway that
// every app service sits behind. See ARCHITECTURE.md for the full picture.
package main

import (
	"context"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
	_ "time/tzdata" // every IANA zone, whatever the image has

	"github.com/acyn-innovation/friday/kernel/internal/access"
	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/gateway"
	"github.com/acyn-innovation/friday/kernel/internal/guss"
	"github.com/acyn-innovation/friday/kernel/internal/inbox"
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
	if weak := svcauth.Weak(databaseURL, map[string]string{"JWT_SECRET": jwtSecret, "KERNEL_EVENTS_TOKEN": eventsToken}); len(weak) > 0 {
		log.Fatalf("set %v: the development value isn't safe outside development (or set FRIDAY_DEV=1)", weak)
	}
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
	// Each sign-in is a device people can see and sign out (Account, Devices).
	issuer.Sessions = &auth.Sessions{Pool: pool, TTL: 24 * time.Hour}
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
		WebURL:   corsOrigin,
	}
	requireAuth := auth.RequireAuth(issuer)

	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"status":"ok","service":"kernel"}`))
	})

	// Passwordless throughout: a passkey ceremony or an emailed one-time
	// code, matching Acyn Wallet's auth model. See internal/auth/handlers.go.
	// The supplier page (plan 12.6): a link from purchasing, then an email code.
	mux.Handle("POST /orgs/supplier-links", requireAuth(http.HandlerFunc(authHandlers.CreateSupplierLink)))
	mux.HandleFunc("POST /supplier/code", authHandlers.SupplierCode)
	mux.HandleFunc("POST /supplier/verify", authHandlers.SupplierVerify)
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
	mux.Handle("GET /auth/passkeys", requireAuth(http.HandlerFunc(issuer.Sessions.ListPasskeys)))
	mux.Handle("DELETE /auth/passkeys/{id}", requireAuth(http.HandlerFunc(issuer.Sessions.DeletePasskey)))
	mux.Handle("GET /auth/sessions", requireAuth(http.HandlerFunc(issuer.Sessions.ListDevices)))
	mux.Handle("DELETE /auth/sessions/{id}", requireAuth(http.HandlerFunc(issuer.Sessions.SignOutDevice)))
	mux.Handle("POST /auth/sessions/sign-out-others", requireAuth(http.HandlerFunc(issuer.Sessions.SignOutOthers)))
	mux.Handle("POST /auth/sessions/sign-out", requireAuth(http.HandlerFunc(issuer.Sessions.SignOutThis)))
	mux.Handle("GET /auth/me", requireAuth(http.HandlerFunc(authHandlers.Me)))
	mux.Handle("POST /auth/sso", requireAuth(http.HandlerFunc(authHandlers.SsoExchange)))
	// Cashier PIN (plan section 11): trusted tills, PINs, lockout.
	mux.HandleFunc("GET /auth/pos/cashiers", authHandlers.PosCashiers)
	mux.HandleFunc("POST /auth/pos/pin", authHandlers.PosPinLogin)
	mux.HandleFunc("POST /auth/pos/approve", authHandlers.PosApprove)
	mux.Handle("POST /auth/pos/resume", requireAuth(http.HandlerFunc(authHandlers.PosResume)))
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
	mux.Handle("POST /orgs/invites", requireAuth(http.HandlerFunc(authHandlers.CreateInvite)))
	mux.Handle("GET /orgs/invites", requireAuth(http.HandlerFunc(authHandlers.ListInvites)))
	mux.Handle("DELETE /orgs/invites/{id}", requireAuth(http.HandlerFunc(authHandlers.RevokeInvite)))
	mux.HandleFunc("GET /invites/{token}", authHandlers.PreviewInvite)
	mux.HandleFunc("POST /invites/{token}/accept", authHandlers.AcceptInviteLink)

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
	people := &org.People{Pool: pool, InternalToken: eventsToken}
	mux.HandleFunc("GET /internal/people/{org_id}", people.AtLocations)
	mux.HandleFunc("GET /internal/people/{org_id}/approvers/{user_id}", people.Approvers)
	mux.HandleFunc("GET /internal/people/{org_id}/person", people.Person)
	mux.Handle("GET /orgs/approval-limits", requireAuth(http.HandlerFunc(people.GetApprovalLimits)))
	mux.Handle("PUT /orgs/approval-limits", requireAuth(http.HandlerFunc(people.PutApprovalLimits)))
	mux.HandleFunc("GET /internal/orgs/{org_id}/time-zone", people.OrgTimeZone)
	mux.Handle("PUT /auth/me/time-zone", requireAuth(http.HandlerFunc(people.SetMyTimeZone)))
	bell := &inbox.Inbox{Pool: pool}
	mux.Handle("GET /me/notifications", requireAuth(http.HandlerFunc(bell.List)))
	mux.Handle("POST /me/notifications/read", requireAuth(http.HandlerFunc(bell.Read)))
	mux.Handle("PATCH /orgs/members/{user_id}", requireAuth(http.HandlerFunc(people.UpdatePerson)))
	mux.Handle("GET /orgs/me/permissions", requireAuth(http.HandlerFunc(people.MyPermissions)))
	mux.Handle("GET /orgs/access/rules", requireAuth(http.HandlerFunc(people.AccessRules)))
	mux.Handle("GET /orgs/locations", requireAuth(http.HandlerFunc(people.Locations)))
	mux.Handle("POST /orgs/locations", requireAuth(http.HandlerFunc(people.SaveLocation)))
	mux.Handle("PATCH /orgs/locations/{id}", requireAuth(http.HandlerFunc(people.SaveLocation)))

	// Integration keys encrypted at rest (RELIABILITY-PLAN phase C); rows
	// stored before the key existed are sealed now.
	secretsBox, err := sealed.New(os.Getenv("FRIDAY_SECRETS_KEY"))
	if err != nil {
		log.Fatal(err)
	}
	if secretsBox == nil {
		log.Printf("FRIDAY_SECRETS_KEY not set: integration keys are stored unencrypted")
	} else {
		// After 10 minutes up: an update that rolls back sooner leaves the
		// old kernel (which can't open sealed rows) with readable keys.
		go func() {
			time.Sleep(10 * time.Minute)
			if n, err := integrations.SealAll(context.Background(), pool, secretsBox); err != nil {
				log.Printf("seal stored integration keys: %v", err)
			} else if n > 0 {
				log.Printf("sealed %d stored integration configs", n)
			}
		}()
	}
	integrationHandlers := &integrations.Handlers{
		Pool:          pool,
		Box:           secretsBox,
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
	mux.HandleFunc("GET /internal/integrations-forwarding/{provider}", integrationHandlers.GetForwarding)
	mux.Handle("POST /orgs/integrations/google_calendar/oauth/start", requireAuth(http.HandlerFunc(integrationHandlers.GoogleOAuthStart)))
	// Not behind requireAuth -- Google's redirect back to this URL carries
	// no Authorization header; see google_oauth.go's oauthStateClaims doc.
	mux.HandleFunc("GET /orgs/integrations/google_calendar/oauth/callback", integrationHandlers.GoogleOAuthCallback)

	gussHandlers := &guss.Handlers{Pool: pool, Box: secretsBox, Issuer: issuer, WebURL: corsOrigin}
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
	mux.HandleFunc("POST /guss/svc/bot", gussHandlers.SetBot)
	mux.HandleFunc("POST /guss/svc/redeem", gussHandlers.Redeem)
	mux.HandleFunc("POST /guss/svc/step-up", gussHandlers.StartStepUp)
	mux.HandleFunc("GET /guss/svc/step-up/{id}", gussHandlers.StepUpStatus)
	mux.HandleFunc("GET /auth/step-up", authHandlers.StepUpInfo)
	mux.HandleFunc("POST /auth/step-up/verify", authHandlers.StepUpVerify)
	mux.Handle("POST /guss/link-code", requireAuth(http.HandlerFunc(gussHandlers.WebLinkCode)))
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
	notices := &inbox.Inbox{Pool: pool}
	go (&gateway.Deliverer{Pool: pool, Apps: apps, Token: eventsToken, Local: map[string]func(context.Context, string, string, string, []byte) error{
		// The inbox first (once per event), then Guss; a Guss failure
		// retries both, and the inbox ignores the repeat.
		"notify": func(ctx context.Context, eventID, orgID, typ string, payload []byte) error {
			if err := notices.Deliver(ctx, eventID, orgID, typ, payload); err != nil {
				return err
			}
			return gussHandlers.Notify(ctx, orgID, typ, payload)
		},
	}}).Run(ctx)
	gateway.WithEventCounts(gateway.EventCounts(pool))
	mux.Handle("GET /health", gateway.HealthHandler(apps, pool, nil))

	gateway.PublicKernelURL, gateway.PublicWebURL = kernelPublicURL, corsOrigin
	for _, app := range apps {
		proxy, err := gateway.NewAppProxy(app)
		if err != nil {
			log.Fatalf("configure proxy for %s: %v", app.Name, err)
		}
		mux.Handle("/api/"+app.Name+"/", requireAuth(gateway.EnforceAccess(app.Name, proxy)))
		if app.Name == "invoicing" {
			// Payment providers' webhooks (each checks its own signature or asks
			// the provider) at this Friday's own address, on whatever domain:
			// <kernel>/external/webhooks/<provider>. Any method: Pesapal calls with GET.
			mux.Handle("/external/webhooks/", proxy)
		}
		log.Printf("routing /api/%s/* -> %s", app.Name, app.BaseURL)
	}

	handler := withCORS(corsOrigin, mux)

	log.Printf("kernel listening on %s", addr)
	// Header timeout stops slow-header connections piling up; no whole-request
	// timeout, so big uploads, exports and slow app replies still finish.
	srv := &http.Server{Addr: addr, Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute}
	if err := srv.ListenAndServe(); err != nil {
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
