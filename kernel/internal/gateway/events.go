package gateway

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"strings"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

type inboundEvent struct {
	Type    string          `json:"type"`
	OrgID   string          `json:"org_id"`
	Payload json.RawMessage `json:"payload"`
}

// subscription is the one cross-app wiring rule in the system: when
// `Event` fires, POST the payload to `App`'s webhook path. Deliberately a
// short static list, not a dynamic pub/sub registry -- see
// ARCHITECTURE.md for why. Add a line here when a new app needs to react
// to another app's event.
type subscription struct {
	Event       string
	App         string
	WebhookPath string
}

var subscriptions = []subscription{
	{Event: "crm.opportunity.won", App: "invoicing", WebhookPath: "/internal/webhooks/crm-won"},
	{Event: "invoicing.pos_sale.recorded", App: "inventory", WebhookPath: "/internal/webhooks/pos-sale"},
}

// EventsHandler receives events apps publish (friday_common.events.publish_event)
// and forwards them to every app subscribed to that event type.
func EventsHandler(apps []registry.App, eventsToken string) http.HandlerFunc {
	byName := map[string]registry.App{}
	for _, a := range apps {
		byName[a.Name] = a
	}

	return func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		if auth != "Bearer "+eventsToken {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		var ev inboundEvent
		if err := json.NewDecoder(r.Body).Decode(&ev); err != nil {
			http.Error(w, "invalid event body", http.StatusBadRequest)
			return
		}

		for _, sub := range subscriptions {
			if sub.Event != ev.Type {
				continue
			}
			app, ok := byName[sub.App]
			if !ok {
				log.Printf("event %s: subscriber app %q not registered", ev.Type, sub.App)
				continue
			}
			go forward(app.BaseURL+sub.WebhookPath, ev, eventsToken)
		}
		w.WriteHeader(http.StatusAccepted)
	}
}

func forward(url string, ev inboundEvent, token string) {
	body, _ := json.Marshal(ev)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		log.Printf("event forward: build request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("event forward to %s failed: %v", url, err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		log.Printf("event forward to %s: status %s", url, strings.TrimSpace(resp.Status))
	}
}
