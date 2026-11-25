package guss

import (
	"strings"
	"testing"
	"time"
)

func TestNoticeTextMoneyAndQuietHours(t *testing.T) {
	if got := money(150000, "kes"); got != "KES 1,500" {
		t.Errorf("money: %q", got)
	}
	if got := money(123456789, "USD"); got != "USD 1,234,567.89" {
		t.Errorf("money with cents: %q", got)
	}
	needed := noticeText("minions.approval.needed",
		notice{FromName: "Sam", AmountCents: 150000, Currency: "KES", Description: "taxi"}, "https://friday.duka.fridayhost.dev/")
	if !strings.Contains(needed, "Sam asks you to approve a claim: KES 1,500 for taxi") ||
		!strings.HasSuffix(needed, "https://friday.duka.fridayhost.dev/minions/team") {
		t.Errorf("needed: %q", needed)
	}
	rejected := noticeText("minions.expense_claim.decided",
		notice{Status: "rejected", DecidedByName: "Tom", Note: "photo is blurry", AmountCents: 1000, Currency: "KES", Description: "taxi"}, "https://x")
	if !strings.Contains(rejected, "Tom rejected your claim for taxi (KES 10): photo is blurry") {
		t.Errorf("rejected: %q", rejected)
	}
	if paid := noticeText("minions.expense_claim.paid", notice{Method: "mpesa", AmountCents: 1000, Currency: "KES", Description: "taxi"}, ""); !strings.HasSuffix(paid, "was paid by M-Pesa.") {
		t.Errorf("paid: %q", paid)
	}
	if noticeText("crm.opportunity.won", notice{}, "") != "" {
		t.Error("other events send nothing")
	}
	at := func(h int) time.Time { return time.Date(2026, 11, 25, h, 0, 0, 0, eat) }
	if !quiet(at(22)) || !quiet(at(6)) || quiet(at(7)) || quiet(at(20)) {
		t.Error("quiet hours are 21:00-07:00 EAT")
	}
}
