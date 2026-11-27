// Package shop is the public side of a business's online shop (Friday
// Host's STOREFRONT-PLAN.md, Commerce slice 1): shop keys, made by owners
// and admins, and a read-only catalogue anyone can fetch with one.
//
// A shop key is public by design (it sits in the shop's page code). It
// only reads what a shopper may see: names, prices, categories, photos
// and whether something is in stock. Never costs, quantities, suppliers
// or people. The kernel turns the key into a short "shop" token for the
// business and asks Inventory, which answers shop tokens on /shop/* only.
package shop

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Via marks a shop token (Claims.Via); Inventory answers it on /shop/*.
const Via = "shop"

// perMinute caps catalogue calls per key (Caddy in front also limits
// each visitor).
const perMinute = 600

type Handlers struct {
	Pool   *pgxpool.Pool
	Issuer *auth.Issuer
	// InventoryURL is Inventory's own address (registry BaseURL).
	InventoryURL string
	HTTP         *http.Client

	mu     sync.Mutex
	window time.Time
	counts map[string]int
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// KeyView is a shop key as its owners see it.
type KeyView struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	Key       string    `json:"key"`
	Origins   []string  `json:"origins"`
	CreatedAt time.Time `json:"created_at"`
}

func owner(w http.ResponseWriter, r *http.Request) (*auth.Claims, bool) {
	c, ok := auth.FromContext(r.Context())
	if !ok || c.Via != "" || (c.Role != "owner" && c.Role != "admin") {
		writeError(w, http.StatusForbidden, "only owners and admins manage shop keys")
		return nil, false
	}
	return c, true
}

// List (GET /orgs/shop-keys): the business's keys still in use.
func (h *Handlers) List(w http.ResponseWriter, r *http.Request) {
	c, ok := owner(w, r)
	if !ok {
		return
	}
	rows, err := h.Pool.Query(r.Context(), `SELECT id::text, name, key, origins, created_at FROM core.shop_keys
		WHERE org_id::text = $1 AND revoked_at IS NULL ORDER BY created_at`, c.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	keys, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (KeyView, error) {
		var k KeyView
		return k, row.Scan(&k.ID, &k.Name, &k.Key, &k.Origins, &k.CreatedAt)
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if keys == nil {
		keys = []KeyView{}
	}
	writeJSON(w, http.StatusOK, keys)
}

// cleanOrigins keeps "https://host[:port]" forms only; empty means any site.
func cleanOrigins(in []string) ([]string, error) {
	out := []string{}
	for _, o := range in {
		o = strings.TrimRight(strings.TrimSpace(strings.ToLower(o)), "/")
		if o == "" {
			continue
		}
		u, err := url.Parse(o)
		if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" || u.Path != "" || u.RawQuery != "" {
			return nil, errors.New("sites look like https://shop.example.com")
		}
		out = append(out, u.Scheme+"://"+u.Host)
	}
	if len(out) > 10 {
		return nil, errors.New("at most 10 sites per key")
	}
	return out, nil
}

// Create (POST /orgs/shop-keys {"name", "origins": [...]}): a new key.
func (h *Handlers) Create(w http.ResponseWriter, r *http.Request) {
	c, ok := owner(w, r)
	if !ok {
		return
	}
	var body struct {
		Name    string   `json:"name"`
		Origins []string `json:"origins"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	name := strings.TrimSpace(body.Name)
	if name == "" || len(name) > 60 {
		name = "Online shop"
	}
	origins, err := cleanOrigins(body.Origins)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	b := make([]byte, 20)
	if _, err := rand.Read(b); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make a key")
		return
	}
	k := KeyView{Name: name, Key: "fpk_" + hex.EncodeToString(b), Origins: origins}
	if err := h.Pool.QueryRow(r.Context(), `INSERT INTO core.shop_keys (org_id, name, key, origins) VALUES ($1::uuid, $2, $3, $4)
		RETURNING id::text, created_at`, c.OrgID, k.Name, k.Key, origins).Scan(&k.ID, &k.CreatedAt); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, k)
}

// Revoke (DELETE /orgs/shop-keys/{id}): stops working at once.
func (h *Handlers) Revoke(w http.ResponseWriter, r *http.Request) {
	c, ok := owner(w, r)
	if !ok {
		return
	}
	tag, err := h.Pool.Exec(r.Context(), `UPDATE core.shop_keys SET revoked_at = now()
		WHERE id::text = $1 AND org_id::text = $2 AND revoked_at IS NULL`, r.PathValue("id"), c.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no such key")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type keyInfo struct {
	id, orgID, currency string
	origins             []string
	suspended           bool
}

func (h *Handlers) lookup(ctx context.Context, key string) (keyInfo, error) {
	var k keyInfo
	err := h.Pool.QueryRow(ctx, `
		SELECT k.id::text, k.org_id::text, k.origins, o.currency, o.suspended_at IS NOT NULL
		FROM core.shop_keys k JOIN core.orgs o ON o.id = k.org_id
		WHERE k.key = $1 AND k.revoked_at IS NULL`, key).Scan(&k.id, &k.orgID, &k.origins, &k.currency, &k.suspended)
	return k, err
}

// allow counts a call against the key's minute.
func (h *Handlers) allow(keyID string) bool { return h.allowN(keyID, perMinute) }

func (h *Handlers) allowN(name string, limit int) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	if now := time.Now(); now.Sub(h.window) >= time.Minute || h.counts == nil {
		h.window, h.counts = now, map[string]int{}
	}
	h.counts[name]++
	return h.counts[name] <= limit
}

// public checks a request's key and site and sets its CORS headers. It
// answers the request itself (and returns false) when it may not go on.
func (h *Handlers) public(w http.ResponseWriter, r *http.Request) (keyInfo, bool) {
	// The kernel's own CORS (Friday's web only) doesn't apply here. Errors
	// carry no shop data, so any site may read why it was refused; data
	// goes only to the key's sites (set below).
	w.Header().Set("Access-Control-Allow-Origin", "*")
	key := r.URL.Query().Get("key")
	if key == "" {
		key = r.Header.Get("Friday-Key")
	}
	if !strings.HasPrefix(key, "fpk_") || len(key) > 80 {
		writeError(w, http.StatusUnauthorized, "add the shop key: ?key=fpk_...")
		return keyInfo{}, false
	}
	k, err := h.lookup(r.Context(), key)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusUnauthorized, "this shop key isn't valid (revoked?)")
		return k, false
	}
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, "try again shortly")
		return k, false
	}
	origin := r.Header.Get("Origin")
	switch {
	case origin == "", len(k.origins) == 0:
	case containsFold(k.origins, origin):
		w.Header().Set("Access-Control-Allow-Origin", origin)
	default:
		writeError(w, http.StatusForbidden, "this shop key isn't for "+origin)
		return k, false
	}
	if k.suspended {
		writeError(w, http.StatusPaymentRequired, "this shop is closed for now")
		return k, false
	}
	if !h.allow(k.id) {
		writeError(w, http.StatusTooManyRequests, "too many requests for this shop; slow down")
		return k, false
	}
	return k, true
}

func containsFold(list []string, s string) bool {
	for _, x := range list {
		if strings.EqualFold(x, s) {
			return true
		}
	}
	return false
}

// inventory asks Inventory's /shop/* for the key's business (GET, or
// POST with a JSON body).
func (h *Handlers) inventory(ctx context.Context, k keyInfo, path string, body ...[]byte) (*http.Response, error) {
	token, err := h.Issuer.IssueVia("shop:"+k.id, k.orgID, Via, "", Via, nil, time.Minute) // role "shop" matches no staff permission
	if err != nil {
		return nil, err
	}
	method, rd := http.MethodGet, io.Reader(nil)
	if len(body) > 0 {
		method, rd = http.MethodPost, bytes.NewReader(body[0])
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(h.InventoryURL, "/")+path, rd)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if rd != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	client := h.HTTP
	if client == nil {
		client = &http.Client{Timeout: 15 * time.Second}
	}
	return client.Do(req)
}

// Catalog (GET /public/catalog?key=fpk_...): what the shop sells.
func (h *Handlers) Catalog(w http.ResponseWriter, r *http.Request) {
	k, ok := h.public(w, r)
	if !ok {
		return
	}
	resp, err := h.inventory(r.Context(), k, "/shop/catalog")
	if err != nil {
		writeError(w, http.StatusBadGateway, "the shop's catalogue isn't reachable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeError(w, http.StatusBadGateway, "the shop's catalogue isn't reachable")
		return
	}
	var products []json.RawMessage
	if err := json.NewDecoder(io.LimitReader(resp.Body, 32<<20)).Decode(&products); err != nil {
		writeError(w, http.StatusBadGateway, "the shop's catalogue isn't readable")
		return
	}
	if products == nil {
		products = []json.RawMessage{}
	}
	w.Header().Set("Cache-Control", "public, max-age=30")
	writeJSON(w, http.StatusOK, map[string]any{"currency": k.currency, "products": products})
}

// Image (GET /public/catalog/products/{id}/image?key=...&v=<sha>).
func (h *Handlers) Image(w http.ResponseWriter, r *http.Request) {
	k, ok := h.public(w, r)
	if !ok {
		return
	}
	id := r.PathValue("id")
	if len(id) != 36 {
		writeError(w, http.StatusNotFound, "no photo")
		return
	}
	resp, err := h.inventory(r.Context(), k, "/shop/products/"+url.PathEscape(id)+"/image")
	if err != nil {
		writeError(w, http.StatusBadGateway, "photo not reachable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeError(w, http.StatusNotFound, "no photo")
		return
	}
	ct := resp.Header.Get("Content-Type")
	if !strings.HasPrefix(ct, "image/") {
		writeError(w, http.StatusNotFound, "no photo")
		return
	}
	w.Header().Set("Content-Type", ct)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	io.Copy(w, io.LimitReader(resp.Body, 8<<20))
}

// orderPerMinute caps orders placed per key: a fake-order flood stays small.
const orderPerMinute = 30

// relay passes Inventory's answer through: its JSON object (with the
// business's currency added) or its error, so the page can say why.
func (h *Handlers) relay(w http.ResponseWriter, k keyInfo, resp *http.Response) {
	var out map[string]any
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil {
		writeError(w, http.StatusBadGateway, "the shop didn't answer clearly")
		return
	}
	if resp.StatusCode < 300 {
		out["currency"] = k.currency
	} else if d, ok := out["detail"]; ok {
		// FastAPI's {"detail": ...}: a message, or {"message", "problems"}.
		out = map[string]any{"error": d}
		if m, ok := d.(map[string]any); ok {
			out = map[string]any{"error": m["message"], "problems": m["problems"]}
		}
	}
	writeJSON(w, resp.StatusCode, out)
}

func (h *Handlers) post(w http.ResponseWriter, r *http.Request, path string, orders bool) {
	k, ok := h.public(w, r)
	if !ok {
		return
	}
	if orders && !h.allowN(k.id+":order", orderPerMinute) {
		writeError(w, http.StatusTooManyRequests, "too many orders from this shop; try again in a minute")
		return
	}
	// Any Content-Type: a page may send text/plain to skip the preflight.
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 32<<10))
	if err != nil || !json.Valid(body) {
		writeError(w, http.StatusBadRequest, "send JSON")
		return
	}
	resp, err := h.inventory(r.Context(), k, path, body)
	if err != nil {
		writeError(w, http.StatusBadGateway, "the shop isn't reachable")
		return
	}
	defer resp.Body.Close()
	h.relay(w, k, resp)
}

// Quote (POST /public/quote?key=): {"lines": [{"product_id", "quantity"}]}
// priced by Friday, with anything that can't be bought.
func (h *Handlers) Quote(w http.ResponseWriter, r *http.Request) { h.post(w, r, "/shop/quote", false) }

// PlaceOrder (POST /public/orders?key=): the basket plus who and how
// (pickup or delivery). Returns the order and its tracking token once.
func (h *Handlers) PlaceOrder(w http.ResponseWriter, r *http.Request) {
	h.post(w, r, "/shop/orders", true)
}

// Track (GET /public/orders/{id}?key=&token=): the order, for its shopper.
func (h *Handlers) Track(w http.ResponseWriter, r *http.Request) {
	k, ok := h.public(w, r)
	if !ok {
		return
	}
	id, token := r.PathValue("id"), r.URL.Query().Get("token")
	if len(id) != 36 || token == "" || len(token) > 100 {
		writeError(w, http.StatusNotFound, "order not found")
		return
	}
	resp, err := h.inventory(r.Context(), k, "/shop/orders/"+url.PathEscape(id)+"?token="+url.QueryEscape(token))
	if err != nil {
		writeError(w, http.StatusBadGateway, "the shop isn't reachable")
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Cache-Control", "no-store")
	h.relay(w, k, resp)
}
