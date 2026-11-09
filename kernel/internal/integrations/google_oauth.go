// Google Calendar OAuth2 -- the one provider in this package whose
// config can't just be pasted into a form. An org admin still creates
// their own OAuth client in Google Cloud Console and pastes
// client_id/client_secret (same bring-your-own-credentials posture as
// Stripe/Slack), but only this flow can turn that into a refresh_token:
// Start mints a signed state and redirects the browser to Google's
// consent screen; Callback is where Google redirects back to, exchanges
// the code, and stores the refresh_token the same way Set does. See
// INTEGRATIONS.md#google-calendar for the admin-facing side of this.
package integrations

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const (
	googleAuthURL  = "https://accounts.google.com/o/oauth2/v2/auth"
	googleTokenURL = "https://oauth2.googleapis.com/token"
	googleScope    = "https://www.googleapis.com/auth/calendar.events"
	oauthStateTTL  = 10 * time.Minute
)

// oauthStateClaims is a short-lived signed token carrying which org
// started the flow -- the only thing standing in for auth on Callback,
// since no Authorization header survives a browser redirect from
// Google. Signed with the same secret as session JWTs (h.JWTSecret);
// it's a different claims shape so it can never be mistaken for one.
type oauthStateClaims struct {
	OrgID    string `json:"org_id"`
	Provider string `json:"provider"`
	jwt.RegisteredClaims
}

func (h *Handlers) signState(orgID, provider string) (string, error) {
	claims := oauthStateClaims{
		OrgID:    orgID,
		Provider: provider,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(oauthStateTTL)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(h.JWTSecret))
}

func (h *Handlers) verifyState(raw, provider string) (orgID string, err error) {
	claims := &oauthStateClaims{}
	_, err = jwt.ParseWithClaims(raw, claims, func(t *jwt.Token) (interface{}, error) {
		return []byte(h.JWTSecret), nil
	})
	if err != nil {
		return "", err
	}
	if claims.Provider != provider {
		return "", fmt.Errorf("state provider mismatch")
	}
	return claims.OrgID, nil
}

// googleRedirectURI must be byte-identical between the authorize-URL
// step and the token-exchange step (Google rejects a mismatch), and is
// also the exact value every org admin registers as an "Authorized
// redirect URI" in their own Google Cloud OAuth client.
func (h *Handlers) googleRedirectURI() string {
	return strings.TrimRight(h.PublicURL, "/") + "/orgs/integrations/google_calendar/oauth/callback"
}

func (h *Handlers) loadGoogleConfig(ctx context.Context, orgID string) (map[string]any, error) {
	var raw []byte
	if err := h.Pool.QueryRow(ctx, `
		SELECT config FROM core.integration_credentials WHERE org_id = $1 AND provider = 'google_calendar'
	`, orgID).Scan(&raw); err != nil {
		return nil, err
	}
	var cfg map[string]any
	_ = json.Unmarshal(raw, &cfg)
	return cfg, nil
}

// GoogleOAuthStart begins the consent flow for the caller's org.
// Requires client_id to already be saved via the regular Set endpoint
// -- this only mints the redirect that turns it into a refresh_token.
func (h *Handlers) GoogleOAuthStart(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}

	cfg, err := h.loadGoogleConfig(r.Context(), claims.OrgID)
	clientID, _ := cfg["client_id"].(string)
	if err != nil || clientID == "" {
		http.Error(w, "save a Google client ID and secret first", http.StatusBadRequest)
		return
	}

	state, err := h.signState(claims.OrgID, "google_calendar")
	if err != nil {
		http.Error(w, "could not start oauth flow", http.StatusInternalServerError)
		return
	}

	q := url.Values{
		"client_id":     {clientID},
		"redirect_uri":  {h.googleRedirectURI()},
		"response_type": {"code"},
		"scope":         {googleScope},
		// offline + consent: without both, Google only issues a
		// refresh_token on an org's very first connect, silently
		// omitting it on every reconnect afterward.
		"access_type": {"offline"},
		"prompt":      {"consent"},
		"state":       {state},
	}
	writeJSON(w, http.StatusOK, map[string]string{"authorize_url": googleAuthURL + "?" + q.Encode()})
}

// GoogleOAuthCallback is where Google redirects the browser back to.
// Deliberately outside requireAuth -- see oauthStateClaims' doc comment
// for why the signed state substitutes for it here.
func (h *Handlers) GoogleOAuthCallback(w http.ResponseWriter, r *http.Request) {
	code := r.URL.Query().Get("code")
	state := r.URL.Query().Get("state")

	orgID, err := h.verifyState(state, "google_calendar")
	if err != nil || code == "" {
		h.redirectResult(w, r, "error")
		return
	}

	cfg, err := h.loadGoogleConfig(r.Context(), orgID)
	clientID, _ := cfg["client_id"].(string)
	clientSecret, _ := cfg["client_secret"].(string)
	if err != nil || clientID == "" || clientSecret == "" {
		h.redirectResult(w, r, "error")
		return
	}

	refreshToken, err := h.exchangeCode(r.Context(), code, clientID, clientSecret)
	if err != nil {
		h.redirectResult(w, r, "error")
		return
	}

	cfg["refresh_token"] = refreshToken
	raw, err := json.Marshal(cfg)
	if err != nil {
		h.redirectResult(w, r, "error")
		return
	}
	// Same upsert shape as Set -- this just populates refresh_token via
	// the OAuth flow instead of a pasted form field.
	if _, err := h.Pool.Exec(r.Context(), `
		INSERT INTO core.integration_credentials (org_id, provider, config, updated_at)
		VALUES ($1, 'google_calendar', $2, now())
		ON CONFLICT (org_id, provider) DO UPDATE SET config = EXCLUDED.config, updated_at = now()
	`, orgID, raw); err != nil {
		h.redirectResult(w, r, "error")
		return
	}

	h.redirectResult(w, r, "connected")
}

func (h *Handlers) exchangeCode(ctx context.Context, code, clientID, clientSecret string) (string, error) {
	form := url.Values{
		"code":          {code},
		"client_id":     {clientID},
		"client_secret": {clientSecret},
		"redirect_uri":  {h.googleRedirectURI()},
		"grant_type":    {"authorization_code"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, googleTokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("google token exchange failed (%d): %s", resp.StatusCode, string(body))
	}

	var out struct {
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return "", err
	}
	if out.RefreshToken == "" {
		return "", fmt.Errorf("no refresh_token in response")
	}
	return out.RefreshToken, nil
}

func (h *Handlers) redirectResult(w http.ResponseWriter, r *http.Request, result string) {
	target := strings.TrimRight(h.CORSOrigin, "/") + "/settings/integrations?google_calendar=" + result
	http.Redirect(w, r, target, http.StatusFound)
}
