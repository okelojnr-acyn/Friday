// Package sealed encrypts integration credentials at rest (Friday Host
// RELIABILITY-PLAN phase C): businesses' Paystack, Stripe, email and
// Google keys were plain JSON in core.integration_credentials, readable by
// anyone who could read the database. AES-256-GCM with FRIDAY_SECRETS_KEY.
//
// A nil *Box (no key set) stores plain JSON, as before, so an install
// without a key keeps working. Rows written before a key existed are
// read as they are and sealed by Box.SealAll at startup. Losing the key
// means re-entering the keys on the Integrations screen; nothing else.
package sealed

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

type Box struct{ aead cipher.AEAD }

// New reads a base64 32-byte key; "" gives nil (no sealing).
func New(keyB64 string) (*Box, error) {
	keyB64 = strings.TrimSpace(keyB64)
	if keyB64 == "" {
		return nil, nil
	}
	key, err := base64.StdEncoding.DecodeString(keyB64)
	if err != nil || len(key) != 32 {
		return nil, errors.New("FRIDAY_SECRETS_KEY must be 32 bytes, base64 (openssl rand -base64 32)")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Box{aead: aead}, nil
}

type envelope struct {
	Sealed string `json:"sealed"`
}

// Seal turns a config's JSON into what is stored: {"sealed": "..."} with
// a key, the JSON itself without one.
func (b *Box) Seal(plain []byte) ([]byte, error) {
	if b == nil {
		return plain, nil
	}
	nonce := make([]byte, b.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	ct := b.aead.Seal(nonce, nonce, plain, nil)
	return json.Marshal(envelope{Sealed: base64.StdEncoding.EncodeToString(ct)})
}

// Open returns a stored config's JSON, sealed or not.
func (b *Box) Open(stored []byte) ([]byte, error) {
	if !IsSealed(stored) {
		return stored, nil
	}
	if b == nil {
		return nil, errors.New("this credential is encrypted but FRIDAY_SECRETS_KEY isn't set")
	}
	var e envelope
	_ = json.Unmarshal(stored, &e)
	ct, err := base64.StdEncoding.DecodeString(e.Sealed)
	if err != nil || len(ct) < b.aead.NonceSize() {
		return nil, errors.New("unreadable sealed credential")
	}
	plain, err := b.aead.Open(nil, ct[:b.aead.NonceSize()], ct[b.aead.NonceSize():], nil)
	if err != nil {
		return nil, fmt.Errorf("can't open this credential (was FRIDAY_SECRETS_KEY changed?): %w", err)
	}
	return plain, nil
}

// IsSealed: the stored JSON is an envelope, not a plain config.
func IsSealed(stored []byte) bool {
	var m map[string]json.RawMessage
	if json.Unmarshal(stored, &m) != nil || len(m) != 1 {
		return false
	}
	_, ok := m["sealed"]
	return ok
}

// Mask is what the browser sees instead of a secret: its last four characters.
const Mask = "•••• "

// IsSecret: a config field holding a key, token or password.
func IsSecret(field string) bool {
	f := strings.ToLower(field)
	for _, s := range []string{"secret", "token", "password", "api_key", "private_key"} {
		if strings.Contains(f, s) {
			return true
		}
	}
	return false
}

// Masked copies cfg with every secret value replaced by Mask + its last 4.
func Masked(cfg map[string]any) map[string]any {
	out := make(map[string]any, len(cfg))
	for k, v := range cfg {
		s, isString := v.(string)
		if IsSecret(k) && isString && s != "" {
			tail := s
			if r := []rune(s); len(r) > 4 {
				tail = string(r[len(r)-4:])
			}
			v = Mask + tail
		}
		out[k] = v
	}
	return out
}

// Merge keeps the stored secret wherever the browser sent back the mask.
func Merge(incoming, stored map[string]any) map[string]any {
	for k, v := range incoming {
		if s, ok := v.(string); ok && IsSecret(k) && strings.HasPrefix(s, Mask) {
			if old, had := stored[k]; had {
				incoming[k] = old
			} else {
				delete(incoming, k)
			}
		}
	}
	return incoming
}
