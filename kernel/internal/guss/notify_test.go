package guss

import (
	"testing"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/inbox"
)

func TestTelegramTextAndQuietHours(t *testing.T) {
	m, _ := inbox.Compose("minions.approval.needed",
		inbox.Notice{FromName: "Sam", AmountCents: 150000, Currency: "KES", Description: "taxi"})
	if got := telegramText(m, "team_leader", "https://friday.duka.fridayhost.dev/"); got !=
		"Sam asks you to approve a claim: KES 1,500 for taxi\nhttps://friday.duka.fridayhost.dev/minions/team" {
		t.Errorf("staff text: %q", got)
	}
	if got := telegramText(m, "owner", "https://x"); got != "Sam asks you to approve a claim: KES 1,500 for taxi\nhttps://x/people/expense_claim" {
		t.Errorf("owner text: %q", got)
	}
	// 19:00 UTC is 22:00 in Nairobi (quiet) but 14:00 in New York (not).
	at := time.Date(2026, 11, 25, 19, 0, 0, 0, time.UTC)
	if !quiet(at, "Africa/Nairobi") || quiet(at, "America/New_York") || quiet(at, "") {
		t.Error("quiet hours are 21:00-07:00 in the person's own zone (UTC when unknown)")
	}
	if quiet(time.Date(2026, 11, 25, 4, 0, 0, 0, time.UTC), "Africa/Nairobi") {
		t.Error("07:00 Nairobi is the end of quiet hours")
	}
}
