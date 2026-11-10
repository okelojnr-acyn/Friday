package gateway

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// Pinger is the one method of the kernel's DB pool HealthHandler needs
// (pgxpool.Pool satisfies it); an interface so tests need no database.
type Pinger interface {
	Ping(ctx context.Context) error
}

type componentHealth struct {
	Status string `json:"status"`
	Error  string `json:"error,omitempty"`
}

type healthReport struct {
	Status string                     `json:"status"`
	Kernel componentHealth            `json:"kernel"`
	Apps   map[string]componentHealth `json:"apps"`
}

// HealthHandler is the install-wide readiness check: the kernel's own
// DB plus every app's GET /health (which itself runs a real query, see
// friday_common.create_app), checked in parallel. 200 only if all are
// ok, else 503 with per-component detail -- the single URL a post-update
// smoke check needs. Unauthenticated on purpose (deploy tooling has no
// session); it exposes only app names and error *classes*, never error
// text that could carry connection details.
//
// Exists because on 2026-11-10 every app's DB access was broken in
// production for days while every liveness check said "ok".
func HealthHandler(apps []registry.App, db Pinger, client *http.Client) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()

		report := healthReport{Status: "ok", Kernel: componentHealth{Status: "ok"}, Apps: map[string]componentHealth{}}
		if err := db.Ping(ctx); err != nil {
			report.Kernel = componentHealth{Status: "error", Error: "db unreachable"}
		}

		var mu sync.Mutex
		var wg sync.WaitGroup
		for _, app := range apps {
			wg.Add(1)
			go func(app registry.App) {
				defer wg.Done()
				h := checkApp(ctx, client, app)
				mu.Lock()
				report.Apps[app.Name] = h
				mu.Unlock()
			}(app)
		}
		wg.Wait()

		healthy := report.Kernel.Status == "ok"
		for _, h := range report.Apps {
			if h.Status != "ok" {
				healthy = false
			}
		}
		status := http.StatusOK
		if !healthy {
			report.Status = "error"
			status = http.StatusServiceUnavailable
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(report)
	})
}

func checkApp(ctx context.Context, client *http.Client, app registry.App) componentHealth {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(app.BaseURL, "/")+"/health", nil)
	if err != nil {
		return componentHealth{Status: "error", Error: "bad app URL"}
	}
	resp, err := client.Do(req)
	if err != nil {
		return componentHealth{Status: "error", Error: "unreachable"}
	}
	defer resp.Body.Close()
	var body struct {
		Status string `json:"status"`
		Error  string `json:"error"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&body)
	if resp.StatusCode == http.StatusOK && body.Status == "ok" {
		return componentHealth{Status: "ok"}
	}
	if body.Error != "" {
		return componentHealth{Status: "error", Error: body.Error}
	}
	return componentHealth{Status: "error", Error: http.StatusText(resp.StatusCode)}
}
