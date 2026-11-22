package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/acyn-innovation/friday/kernel/internal/access"
)

// The supplier page (plan 12.6, 12.8 step 7). Whoever buys for the
// business makes a link for one supplier; the supplier opens it, gets a
// code at the email on the link, and gets a short session that reaches
// only Inventory's /supplier routes (RequireAuth), where they see their
// own purchase orders.

// SupplierVia marks a supplier's session.
const SupplierVia = "supplier"

const (
	supplierLinkTTL    = 90 * 24 * time.Hour
	supplierSessionTTL = 12 * time.Hour
)

func supplierTokenHash(t string) string {
	h := sha256.Sum256([]byte("supplier:" + t))
	return hex.EncodeToString(h[:])
}

// CreateSupplierLink (POST /orgs/supplier-links): {"supplier_id",
// "supplier_name", "email"} -> {"link", "expires_in"}. People who buy
// (purchasing.write); a new link replaces the supplier's old one.
func (h *Handlers) CreateSupplierLink(w http.ResponseWriter, r *http.Request) {
	c, ok := FromContext(r.Context())
	if !ok || c.Via != "" || access.Scope("purchasing.write", c.Role, c.Perms) == "" {
		writeError(w, http.StatusForbidden, "only people who buy for the business can share purchase orders with suppliers")
		return
	}
	var body struct {
		SupplierID   string `json:"supplier_id"`
		SupplierName string `json:"supplier_name"`
		Email        string `json:"email"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil || len(body.SupplierID) != 36 {
		writeError(w, http.StatusBadRequest, `send {"supplier_id": "...", "supplier_name": "...", "email": "..."}`)
		return
	}
	addr, err := mail.ParseAddress(strings.TrimSpace(body.Email))
	if err != nil {
		writeError(w, http.StatusBadRequest, "the supplier needs an email address for their sign-in codes")
		return
	}
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make a link")
		return
	}
	t := base64.RawURLEncoding.EncodeToString(b)
	ctx := r.Context()
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `UPDATE core.supplier_links SET revoked_at = now()
		WHERE org_id::text = $1 AND supplier_id::text = $2 AND revoked_at IS NULL`, c.OrgID, body.SupplierID); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if _, err := tx.Exec(ctx, `INSERT INTO core.supplier_links
		(org_id, supplier_id, supplier_name, email, token_hash, created_by, expires_at)
		VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::uuid, $7)`,
		c.OrgID, body.SupplierID, strings.TrimSpace(body.SupplierName), strings.ToLower(addr.Address),
		supplierTokenHash(t), nullUUID(c.Subject), time.Now().Add(supplierLinkTTL)); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the link")
		return
	}
	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	log.Printf("supplier link made: org %s, supplier %s, by %s", c.OrgID, body.SupplierID, c.Subject)
	writeJSON(w, http.StatusCreated, map[string]any{
		"link":       strings.TrimRight(h.WebURL, "/") + "/supplier?t=" + t,
		"expires_in": int(supplierLinkTTL.Seconds()),
	})
}

// nullUUID: the creator's id when it is one (a Friday Host SSO token's
// subject isn't a Friday user).
func nullUUID(s string) any {
	if len(s) == 36 {
		return s
	}
	return nil
}

type supplierLink struct {
	id, orgID, supplierID, name, email, orgName string
}

func (h *Handlers) openSupplierLink(r *http.Request, t string) (supplierLink, error) {
	var l supplierLink
	err := h.Pool.QueryRow(r.Context(), `
		SELECT l.id::text, l.org_id::text, l.supplier_id::text, l.supplier_name, l.email, o.name
		FROM core.supplier_links l JOIN core.orgs o ON o.id = l.org_id
		WHERE l.token_hash = $1 AND l.revoked_at IS NULL AND l.expires_at > now()`, supplierTokenHash(t),
	).Scan(&l.id, &l.orgID, &l.supplierID, &l.name, &l.email, &l.orgName)
	return l, err
}

// hideEmail: "sales@acme.co.ke" -> "s***@acme.co.ke".
func hideEmail(e string) string {
	user, domain, ok := strings.Cut(e, "@")
	if !ok || user == "" {
		return "your email"
	}
	return user[:1] + "***@" + domain
}

// SupplierCode (POST /supplier/code): {"t"} -> emails a code to the
// address on the link; {"email_hint", "business", "supplier"}.
func (h *Handlers) SupplierCode(w http.ResponseWriter, r *http.Request) {
	var body struct {
		T string `json:"t"`
	}
	json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body)
	l, err := h.openSupplierLink(r, body.T)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "this link has expired or was replaced; ask the business for a new one")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	code, err := h.Otp.Request(r.Context(), l.email, "supplier:"+l.id, nil)
	if err != nil {
		writeError(w, http.StatusTooManyRequests, err.Error())
		return
	}
	if h.Mailer != nil {
		if err := h.Mailer.Send(l.email, "Your code for "+l.orgName,
			fmt.Sprintf("Your code to see %s's purchase orders: %s\n\nIt works for 10 minutes. If you didn't ask for it, ignore this email.", l.orgName, code)); err != nil {
			log.Printf("supplier code email for link %s: %v", l.id, err)
			writeError(w, http.StatusBadGateway, "couldn't send the email; try again")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]string{"email_hint": hideEmail(l.email), "business": l.orgName, "supplier": l.name})
}

// SupplierVerify (POST /supplier/verify): {"t", "code"} -> a 12-hour
// session that reaches only Inventory's /supplier routes.
func (h *Handlers) SupplierVerify(w http.ResponseWriter, r *http.Request) {
	var body struct {
		T    string `json:"t"`
		Code string `json:"code"`
	}
	json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body)
	l, err := h.openSupplierLink(r, body.T)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "this link has expired or was replaced; ask the business for a new one")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if _, err := h.Otp.Verify(r.Context(), l.email, "supplier:"+l.id, strings.TrimSpace(body.Code)); err != nil {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}
	token, err := h.Issuer.IssueVia("supplier:"+l.supplierID, l.orgID, SupplierVia, l.email, SupplierVia,
		map[string]string{"inventory": "write"}, supplierSessionTTL)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue a session")
		return
	}
	log.Printf("supplier signed in: org %s, supplier %s", l.orgID, l.supplierID)
	writeJSON(w, http.StatusOK, map[string]any{
		"token": token, "expires_in": int(supplierSessionTTL.Seconds()), "business": l.orgName, "supplier": l.name,
	})
}
