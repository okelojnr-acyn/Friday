// Package mail sends the one kind of email the kernel ever needs to
// send: a passwordless-login OTP code. Three transports, tried in
// order, each a strict superset of config needed for local dev to work
// with zero setup:
//
//  1. Resend (RESEND_API_KEY set) -- a plain REST call, no vendor SDK
//     dependency, same "no dependency we don't need" posture as
//     friday_common/integrations/stripe.py. Recommended default: Acyn
//     Wallet (whose auth model this mirrors) uses Resend too, and its
//     free tier needs nothing but an API key and a verified sender --
//     see INSTALL.md for exactly where to get one.
//  2. Generic SMTP (SMTP_HOST set) -- works against any SMTP relay
//     (a self-hosted Postfix, Mailtrap/Mailpit for staging, or any
//     other provider's SMTP endpoint) for deployments that already
//     have one and don't want a second mail vendor.
//  3. Dev-mode stdout log (neither set) -- the OTP code just shows up
//     in the kernel's own log output. Every local run and CI job works
//     with no mail server at all.
package mail

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/smtp"
	"os"
	"time"
)

type Mailer struct {
	resendAPIKey       string
	smtpHost, smtpPort string
	smtpUser, smtpPass string
	from               string
	httpClient         *http.Client
}

func New() *Mailer {
	return &Mailer{
		resendAPIKey: os.Getenv("RESEND_API_KEY"),
		smtpHost:     os.Getenv("SMTP_HOST"),
		smtpPort:     envOr("SMTP_PORT", "587"),
		smtpUser:     os.Getenv("SMTP_USER"),
		smtpPass:     os.Getenv("SMTP_PASS"),
		from:         envOr("MAIL_FROM", envOr("SMTP_FROM", "Friday <no-reply@localhost>")),
		httpClient:   &http.Client{Timeout: 10 * time.Second},
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// Send delivers a plain-text email over whichever transport is
// configured, trying Resend, then SMTP, then falling back to a stdout
// log -- see the package doc comment for the full cascade.
func (m *Mailer) Send(to, subject, body string) error {
	if m.resendAPIKey != "" {
		return m.sendViaResend(to, subject, body)
	}
	if m.smtpHost != "" {
		return m.sendViaSMTP(to, subject, body)
	}
	log.Printf("[mail:dev] to=%s subject=%q\n%s", to, subject, body)
	return nil
}

type resendRequest struct {
	From    string `json:"from"`
	To      string `json:"to"`
	Subject string `json:"subject"`
	Text    string `json:"text"`
}

func (m *Mailer) sendViaResend(to, subject, body string) error {
	payload, err := json.Marshal(resendRequest{From: m.from, To: to, Subject: subject, Text: body})
	if err != nil {
		return fmt.Errorf("mail: encode resend request: %w", err)
	}
	req, err := http.NewRequest(http.MethodPost, "https://api.resend.com/emails", bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("mail: build resend request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+m.resendAPIKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := m.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("mail: resend request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("mail: resend returned status %d", resp.StatusCode)
	}
	return nil
}

func (m *Mailer) sendViaSMTP(to, subject, body string) error {
	msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\n\r\n%s\r\n", m.from, to, subject, body)
	addr := m.smtpHost + ":" + m.smtpPort
	var auth smtp.Auth
	if m.smtpUser != "" {
		auth = smtp.PlainAuth("", m.smtpUser, m.smtpPass, m.smtpHost)
	}
	return smtp.SendMail(addr, auth, m.from, []string{to}, []byte(msg))
}
