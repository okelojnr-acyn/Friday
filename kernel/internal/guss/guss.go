// Package guss lets Friday's web app talk to the org's Guss (the shop
// assistant) through the kernel. The org saves Guss's address and token
// as the "guss" integration; the browser never sees the token, it only
// calls these routes with its Friday session.
package guss

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

type Handlers struct {
	Pool *pgxpool.Pool
	// Client is replaced in tests; nil means the SSRF-safe default.
	Client *http.Client
}

type config struct {
	URL   string `json:"url"`
	Token string `json:"token"`
}

var errNotConnected = errors.New("Guss isn't connected for this organisation")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func (h *Handlers) load(ctx context.Context, orgID string) (config, error) {
	var raw []byte
	err := h.Pool.QueryRow(ctx,
		`SELECT config FROM core.integration_credentials WHERE org_id = $1 AND provider = 'guss'`, orgID).Scan(&raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return config{}, errNotConnected
	}
	if err != nil {
		return config{}, err
	}
	var c config
	if json.Unmarshal(raw, &c) != nil || c.URL == "" || c.Token == "" {
		return config{}, errNotConnected
	}
	return c, nil
}

// validURL accepts only https URLs with a host name or public IP.
func validURL(raw string) (*url.URL, error) {
	u, err := url.Parse(strings.TrimRight(strings.TrimSpace(raw), "/"))
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil {
		return nil, errors.New("Guss's address must be an https:// URL")
	}
	return u, nil
}

// blockPrivate refuses connections to loopback, private, link-local and
// other non-public addresses, checked on the address actually dialled
// (after DNS), so a saved URL can't be used to reach the kernel's own
// network.
func blockPrivate(_, address string, _ syscall.RawConn) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return err
	}
	ip := net.ParseIP(host)
	if ip == nil || ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() ||
		ip.IsUnspecified() || ip.IsMulticast() || ip.IsInterfaceLocalMulticast() {
		return fmt.Errorf("refusing to connect to non-public address %s", host)
	}
	return nil
}

func (h *Handlers) client() *http.Client {
	if h.Client != nil {
		return h.Client
	}
	dialer := &net.Dialer{Timeout: 10 * time.Second, Control: blockPrivate}
	return &http.Client{
		Timeout: 60 * time.Second,
		Transport: &http.Transport{
			DialContext:         dialer.DialContext,
			TLSHandshakeTimeout: 10 * time.Second,
			MaxIdleConns:        10,
			IdleConnTimeout:     60 * time.Second,
		},
		// Guss answers directly; a redirect could point anywhere.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

// call forwards one request to Guss and returns its {"reply": ...}.
func (h *Handlers) call(ctx context.Context, c config, method, path string, body any) (string, int, error) {
	base, err := validURL(c.URL)
	if err != nil {
		return "", http.StatusBadRequest, err
	}
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, base.String()+path, rd)
	if err != nil {
		return "", http.StatusBadGateway, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := h.client().Do(req)
	if err != nil {
		return "", http.StatusBadGateway, errors.New("couldn't reach Guss; check it's running and its address on the Integrations page")
	}
	defer resp.Body.Close()
	var out struct {
		Reply string `json:"reply"`
		Error string `json:"error"`
	}
	json.NewDecoder(io.LimitReader(resp.Body, 64<<10)).Decode(&out)
	switch {
	case resp.StatusCode == http.StatusUnauthorized:
		return "", http.StatusBadGateway, errors.New("Guss refused the token saved on the Integrations page")
	case resp.StatusCode >= 400:
		msg := out.Error
		if msg == "" {
			msg = fmt.Sprintf("Guss answered %d", resp.StatusCode)
		}
		status := http.StatusBadGateway
		if resp.StatusCode == http.StatusBadRequest || resp.StatusCode == http.StatusTooManyRequests {
			status = resp.StatusCode
		}
		return "", status, errors.New(msg)
	}
	return out.Reply, http.StatusOK, nil
}

// Status says whether Guss is connected (GET /guss/status, any member).
func (h *Handlers) Status(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, err := h.load(r.Context(), claims.OrgID)
	if err != nil && !errors.Is(err, errNotConnected) {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"connected": err == nil})
}

// Chat sends a message to Guss (POST /guss/chat). Recording sales and
// stock writes to the books, so viewers can't.
func (h *Handlers) Chat(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if claims.Role == "viewer" {
		writeError(w, http.StatusForbidden, "viewers can read reports but can't record anything")
		return
	}
	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	c, err := h.load(r.Context(), claims.OrgID)
	if err != nil {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	// One conversation per Friday user, so "undo" undoes your own entry.
	reply, status, err := h.call(r.Context(), c, http.MethodPost, "/api/chat",
		map[string]string{"conversation_id": "friday:" + claims.Subject, "text": req.Text})
	if err != nil {
		writeError(w, status, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"reply": reply})
}

// Report returns Guss's day/week/month report (GET /guss/report?window=).
func (h *Handlers) Report(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	window := r.URL.Query().Get("window")
	if window != "day" && window != "week" && window != "month" {
		writeError(w, http.StatusBadRequest, "window must be day, week or month")
		return
	}
	c, err := h.load(r.Context(), claims.OrgID)
	if err != nil {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	reply, status, err := h.call(r.Context(), c, http.MethodGet, "/api/report?window="+window, nil)
	if err != nil {
		writeError(w, status, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"reply": reply})
}
