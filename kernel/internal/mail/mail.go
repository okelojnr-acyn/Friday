// Package mail sends the one kind of email the kernel ever needs to
// send: a passwordless-login OTP code. Deliberately plain SMTP (net/smtp,
// stdlib only) rather than a vendor SDK -- it works against any SMTP
// relay (a real provider's SMTP endpoint, Mailtrap/Mailpit for staging, a
// self-hosted Postfix), so adopting Friday never means adopting a
// specific email vendor at the auth layer.
package mail

import (
	"fmt"
	"log"
	"net/smtp"
	"os"
)

type Mailer struct {
	host, port, user, pass, from string
}

func New() *Mailer {
	return &Mailer{
		host: os.Getenv("SMTP_HOST"),
		port: envOr("SMTP_PORT", "587"),
		user: os.Getenv("SMTP_USER"),
		pass: os.Getenv("SMTP_PASS"),
		from: envOr("SMTP_FROM", "Friday <no-reply@localhost>"),
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// Send delivers a plain-text email, or -- if SMTP_HOST was never set --
// logs it to stdout instead. This is what makes local dev and CI work
// with zero mail-server setup: the OTP code just shows up in the
// kernel's own log output. A real deployment sets SMTP_HOST (and
// friends) and gets real delivery with no code change on either side.
func (m *Mailer) Send(to, subject, body string) error {
	if m.host == "" {
		log.Printf("[mail:dev] to=%s subject=%q\n%s", to, subject, body)
		return nil
	}
	msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\n\r\n%s\r\n", m.from, to, subject, body)
	addr := m.host + ":" + m.port
	var auth smtp.Auth
	if m.user != "" {
		auth = smtp.PlainAuth("", m.user, m.pass, m.host)
	}
	return smtp.SendMail(addr, auth, m.from, []string{to}, []byte(msg))
}
