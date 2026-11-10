package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

type fakePinger struct{ err error }

func (f fakePinger) Ping(context.Context) error { return f.err }

func appServer(status int, body string) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			http.NotFound(w, r)
			return
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
}

func runHealth(t *testing.T, apps []registry.App, db Pinger) (int, healthReport) {
	t.Helper()
	rec := httptest.NewRecorder()
	HealthHandler(apps, db, nil).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/health", nil))
	var rep healthReport
	if err := json.Unmarshal(rec.Body.Bytes(), &rep); err != nil {
		t.Fatalf("decode: %v (%s)", err, rec.Body.String())
	}
	return rec.Code, rep
}

func TestHealthAllOK(t *testing.T) {
	a := appServer(200, `{"status":"ok","db":"ok"}`)
	defer a.Close()
	code, rep := runHealth(t, []registry.App{{Name: "crm", BaseURL: a.URL}}, fakePinger{})
	if code != 200 || rep.Status != "ok" || rep.Apps["crm"].Status != "ok" {
		t.Fatalf("got %d %+v", code, rep)
	}
}

// The 2026-11-10 failure shape: process up, DB broken.
func TestHealthReportsAppDBFailure(t *testing.T) {
	ok := appServer(200, `{"status":"ok"}`)
	defer ok.Close()
	broken := appServer(503, `{"status":"error","error":"TypeError"}`)
	defer broken.Close()
	code, rep := runHealth(t, []registry.App{
		{Name: "crm", BaseURL: broken.URL},
		{Name: "fleets", BaseURL: ok.URL},
	}, fakePinger{})
	if code != http.StatusServiceUnavailable || rep.Status != "error" {
		t.Fatalf("want 503/error, got %d %+v", code, rep)
	}
	if rep.Apps["crm"].Error != "TypeError" || rep.Apps["fleets"].Status != "ok" {
		t.Fatalf("per-app detail wrong: %+v", rep.Apps)
	}
}

func TestHealthReportsUnreachableAppAndKernelDB(t *testing.T) {
	code, rep := runHealth(t, []registry.App{{Name: "crm", BaseURL: "http://127.0.0.1:1"}}, fakePinger{err: errors.New("down")})
	if code != http.StatusServiceUnavailable || rep.Kernel.Status != "error" || rep.Apps["crm"].Error != "unreachable" {
		t.Fatalf("got %d %+v", code, rep)
	}
}
