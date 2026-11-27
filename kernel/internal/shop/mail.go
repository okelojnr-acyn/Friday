package shop

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Sender is the kernel's mailer.
type Sender interface {
	Send(to, subject, body string) error
}

// Mail emails a shopper when their order is placed, paid, ready or
// cancelled (event inventory.shop_order.updated, delivered locally).
type Mail struct {
	Pool   *pgxpool.Pool
	Mailer Sender
}

func money(cents int64, currency string) string {
	return fmt.Sprintf("%s %d.%02d", currency, cents/100, cents%100)
}

// Deliver is a gateway.Deliverer Local subscriber. A failed send returns
// the error, so the event is retried.
func (m *Mail) Deliver(ctx context.Context, eventID, orgID, typ string, payload []byte) error {
	var o struct {
		Number       string `json:"number"`
		Status       string `json:"status"`
		Email        string `json:"email"`
		CustomerName string `json:"customer_name"`
		Fulfilment   string `json:"fulfilment"`
		TotalCents   int64  `json:"total_cents"`
	}
	if err := json.Unmarshal(payload, &o); err != nil || o.Email == "" || m.Mailer == nil {
		return nil // nothing to send; never retry a bad payload
	}
	if o.CustomerName = strings.TrimSpace(o.CustomerName); o.CustomerName == "" {
		o.CustomerName = "there"
	}
	var shop, currency string
	if err := m.Pool.QueryRow(ctx, `SELECT name, currency FROM core.orgs WHERE id::text = $1`, orgID).Scan(&shop, &currency); err != nil {
		return err
	}
	total := money(o.TotalCents, currency)
	var subject, line string
	switch o.Status {
	case "placed":
		subject, line = "We've got your order "+o.Number, "Thanks for your order of "+total+". We'll be in touch once it's paid."
	case "paid":
		subject, line = "Order "+o.Number+" is paid", "We've received "+total+" and are getting your order ready."
	case "ready":
		subject = "Order " + o.Number + " is ready"
		line = "Your order is ready to collect."
		if o.Fulfilment == "delivery" {
			line = "Your order is on its way to you."
		}
	case "cancelled":
		subject, line = "Order "+o.Number+" is cancelled", "Your order has been cancelled. If you paid, the money is coming back to you."
	default:
		return nil
	}
	body := fmt.Sprintf("Hello %s,\n\n%s\n\nOrder %s, %s.\n\n%s", o.CustomerName, line, o.Number, total, shop)
	return m.Mailer.Send(o.Email, subject+" · "+shop, body)
}
