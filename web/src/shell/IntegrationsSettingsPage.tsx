import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import {
  deleteIntegration,
  getIntegration,
  listIntegrations,
  setIntegration,
  startGoogleCalendarOAuth,
} from "../lib/integrations";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FieldWrap, Input } from "../ui/Field";
import { Icon, type IconName } from "../ui/Icon";

interface ProviderField {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
}

interface ProviderDescriptor {
  key: string;
  label: string;
  icon: IconName;
  category: string;
  codeReady: boolean;
  docAnchor: string;
  fields: ProviderField[];
  // True only for google_calendar today -- renders a "Connect with
  // Google" button (kernel/internal/integrations/google_oauth.go) that
  // turns a saved client_id/client_secret into a refresh_token, instead
  // of expecting the admin to paste one in by hand.
  oauth?: boolean;
}

// One row per provider INTEGRATIONS.md documents. `codeReady` providers
// (Stripe, Slack, Acyn Wallet) have a real adapter behind
// friday_common.integrations already calling out with whatever gets
// saved here; the rest are stubs a fork finishes -- see
// INTEGRATIONS.md#<docAnchor> for exactly what each one needs.
const PROVIDERS: ProviderDescriptor[] = [
  {
    key: "stripe",
    label: "Stripe",
    icon: "credit-card",
    category: "Payments",
    codeReady: true,
    docAnchor: "stripe",
    fields: [
      { key: "secret_key", label: "Secret key", secret: true, placeholder: "sk_live_..." },
      { key: "webhook_secret", label: "Webhook secret", secret: true, placeholder: "whsec_..." },
    ],
  },
  {
    key: "slack",
    label: "Slack",
    icon: "message-circle",
    category: "Notifications",
    codeReady: true,
    docAnchor: "slack",
    fields: [{ key: "webhook_url", label: "Incoming webhook URL", placeholder: "https://hooks.slack.com/..." }],
  },
  {
    key: "resend",
    label: "Resend",
    icon: "mail",
    category: "Notifications",
    codeReady: true,
    docAnchor: "resend",
    fields: [
      { key: "api_key", label: "API key", secret: true, placeholder: "re_..." },
      { key: "from_email", label: "From address (optional)", placeholder: "Acme <billing@acme.com>" },
    ],
  },
  {
    key: "acyn_wallet",
    label: "Acyn Wallet",
    icon: "wallet",
    category: "Web3",
    codeReady: true,
    docAnchor: "acyn-wallet",
    fields: [{ key: "api_key", label: "Partner API key", secret: true, placeholder: "pk_live_..." }],
  },
  {
    key: "coingecko",
    label: "CoinGecko",
    icon: "trend-up",
    category: "Market Data",
    codeReady: true,
    docAnchor: "coingecko",
    // No required fields -- the free API needs no key at all, and the
    // watchlist (a list, not a string) is edited from the Web3 app's
    // Market page itself (MarketPage.tsx), not here, so this form never
    // round-trips it through a plain text input and corrupts it into a
    // string. Pro API key is the only thing this screen actually manages.
    fields: [{ key: "api_key", label: "Pro API key (optional)", secret: true }],
  },
  {
    key: "calendly",
    label: "Calendly",
    icon: "calendar",
    category: "Scheduling",
    codeReady: false,
    docAnchor: "calendly",
    fields: [{ key: "api_key", label: "Personal access token", secret: true }],
  },
  {
    key: "google_calendar",
    label: "Google Calendar",
    icon: "calendar",
    category: "Scheduling",
    codeReady: true,
    docAnchor: "google-calendar",
    oauth: true,
    // No refresh_token field -- that's what "Connect with Google"
    // produces, pasting one in by hand isn't a thing here.
    fields: [
      { key: "client_id", label: "Client ID" },
      { key: "client_secret", label: "Client secret", secret: true },
    ],
  },
  {
    key: "paystack",
    label: "Paystack",
    icon: "credit-card",
    category: "Payments",
    codeReady: false,
    docAnchor: "paystack",
    fields: [{ key: "secret_key", label: "Secret key", secret: true }],
  },
  {
    key: "pesapal",
    label: "Pesapal",
    icon: "credit-card",
    category: "Payments",
    codeReady: true,
    docAnchor: "pesapal",
    fields: [
      { key: "consumer_key", label: "Consumer key" },
      { key: "consumer_secret", label: "Consumer secret", secret: true },
    ],
  },
  {
    key: "atlas",
    label: "MongoDB Atlas",
    icon: "database",
    category: "BaaS",
    codeReady: false,
    docAnchor: "atlas",
    fields: [
      { key: "public_key", label: "Public key" },
      { key: "private_key", label: "Private key", secret: true },
      { key: "project_id", label: "Project ID" },
    ],
  },
  {
    key: "bridge",
    label: "Bridge",
    icon: "link-2",
    category: "Web3",
    codeReady: false,
    docAnchor: "bridge",
    fields: [{ key: "api_key", label: "API key", secret: true }],
  },
  {
    key: "alchemy",
    label: "Alchemy",
    icon: "link-2",
    category: "Web3",
    codeReady: false,
    docAnchor: "alchemy",
    fields: [{ key: "api_key", label: "API key", secret: true }],
  },
  {
    key: "turnkey",
    label: "Turnkey",
    icon: "shield-check",
    category: "Web3",
    codeReady: false,
    docAnchor: "turnkey",
    fields: [
      { key: "api_public_key", label: "API public key" },
      { key: "api_private_key", label: "API private key", secret: true },
      { key: "organization_id", label: "Organization ID" },
    ],
  },
];

function ProviderCard({
  provider,
  connected,
  canManage,
  onChanged,
}: {
  provider: ProviderDescriptor;
  connected: boolean;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  // The full stored config, as-is -- a provider's config can hold keys
  // this form never shows (CoinGecko's `watchlist` array is edited from
  // apps/web3's Market page, not here). Saving merges `values` into this
  // rather than replacing the whole config, so editing one field here
  // never silently drops a key this screen doesn't know about.
  const [rawConfig, setRawConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function openEditor() {
    setEditing(true);
    setError(null);
    if (!connected) return;
    setLoading(true);
    try {
      const cred = await getIntegration(provider.key);
      setRawConfig(cred.config);
      setValues(Object.fromEntries(provider.fields.map((f) => [f.key, String(cred.config[f.key] ?? "")])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load config");
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await setIntegration(provider.key, { ...rawConfig, ...values });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    setSaving(true);
    setError(null);
    try {
      await deleteIntegration(provider.key);
      setEditing(false);
      setValues({});
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect");
    } finally {
      setSaving(false);
    }
  }

  // Requires client_id/client_secret to already be saved (Save must
  // happen first) -- the kernel 400s GoogleOAuthStart otherwise, same
  // check mirrored here so the button reads as disabled instead of
  // bouncing the admin off to Google only to fail server-side.
  const canConnectGoogle = Boolean(values.client_id?.trim() && values.client_secret?.trim());
  const googleConnected = Boolean(rawConfig.refresh_token);

  async function connectGoogle() {
    setConnecting(true);
    setError(null);
    try {
      await save();
      const { authorize_url } = await startGoogleCalendarOAuth();
      window.location.href = authorize_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start Google connect");
      setConnecting(false);
    }
  }

  return (
    <Card style={{ marginBottom: 12 }}>
      <div className="page-header" style={{ marginBottom: editing ? 12 : 0 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Icon name={provider.icon} size={20} />
          <div>
            <div style={{ fontWeight: 500 }}>{provider.label}</div>
            <div className="field-label">{provider.category}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {provider.codeReady ? <Badge tone="accent">Code-ready</Badge> : <Badge tone="neutral">Stub</Badge>}
          <Badge tone={connected ? "success" : "neutral"}>{connected ? "Connected" : "Not connected"}</Badge>
          {canManage ? (
            <Button size="sm" variant="secondary" onClick={openEditor} disabled={editing}>
              {connected ? "Edit" : "Connect"}
            </Button>
          ) : null}
        </div>
      </div>

      {editing ? (
        loading ? (
          <div className="spinner">Loading...</div>
        ) : (
          <div>
            {error ? <div className="error-banner" style={{ marginBottom: 10 }}>{error}</div> : null}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {provider.fields.map((f) => (
                <FieldWrap key={f.key} label={f.label}>
                  <Input
                    type={f.secret ? "password" : "text"}
                    placeholder={f.placeholder}
                    value={values[f.key] ?? ""}
                    onChange={(e) => setValues((cur) => ({ ...cur, [f.key]: e.target.value }))}
                    style={{ width: 220 }}
                  />
                </FieldWrap>
              ))}
            </div>
            {provider.oauth ? (
              <div className="field-label" style={{ marginTop: 10 }}>
                {googleConnected
                  ? "Connected to a Google Calendar account."
                  : "Save the client ID/secret above, then connect to get a refresh token."}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <Button size="sm" variant="primary" onClick={save} disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </Button>
              {provider.oauth ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={connectGoogle}
                  disabled={saving || connecting || !canConnectGoogle}
                >
                  {connecting ? "Connecting..." : googleConnected ? "Reconnect with Google" : "Connect with Google"}
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving || connecting}>
                Cancel
              </Button>
              {connected ? (
                <Button size="sm" variant="danger" onClick={disconnect} disabled={saving || connecting}>
                  Disconnect
                </Button>
              ) : null}
            </div>
          </div>
        )
      ) : null}
    </Card>
  );
}

/** Settings > Integrations: one card per provider INTEGRATIONS.md
 * documents, backed by kernel/internal/integrations. `GET
 * /orgs/integrations` (connected-status only, every role can call it) is
 * fetched once here; each card's own config is fetched lazily on "Edit"
 * through the admin-gated `GET /orgs/integrations/{provider}" so a
 * provider's secret never reaches a role that shouldn't see it (see
 * that handler's own doc comment). */
export function IntegrationsSettingsPage() {
  const { session } = useAuth();
  const [connected, setConnected] = useState<Set<string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const canManage = session?.role === "owner" || session?.role === "admin";

  function load() {
    listIntegrations()
      .then((rows) => setConnected(new Set(rows.map((r) => r.provider))))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load integrations"));
  }

  useEffect(load, []);

  // Where kernel/internal/integrations/google_oauth.go's Callback lands
  // the browser back after the Google consent redirect finishes. Read
  // once, then strip it so refreshing the page doesn't re-show it.
  const googleCalendarResult = searchParams.get("google_calendar");
  useEffect(() => {
    if (!googleCalendarResult) return;
    const next = new URLSearchParams(searchParams);
    next.delete("google_calendar");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [googleCalendarResult]);

  if (!connected) return <div className="page spinner">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Integrations</h1>
      </div>
      {googleCalendarResult === "connected" ? (
        <div style={{ marginBottom: 16 }}>
          <Badge tone="success">Google Calendar connected</Badge>
        </div>
      ) : null}
      {googleCalendarResult === "error" ? (
        <div className="error-banner" style={{ marginBottom: 16 }}>
          Could not connect Google Calendar -- check the client ID/secret and try again.
        </div>
      ) : null}
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      <p className="field-label" style={{ marginBottom: 16 }}>
        Connect a provider with the API key or webhook URL it gives you -- see INTEGRATIONS.md for what each one
        needs and whether it's wired up already or a stub to finish.
      </p>
      {PROVIDERS.map((p) => (
        <ProviderCard key={p.key} provider={p} connected={connected.has(p.key)} canManage={canManage} onChanged={load} />
      ))}
    </div>
  );
}
