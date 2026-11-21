import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { deleteIntegration, getIntegration, setIntegration, startGoogleCalendarOAuth } from "../lib/integrations";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import type { IconName } from "../ui/Icon";

export interface ProviderField {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
}

export interface ProviderDescriptor {
  key: string;
  label: string;
  /** The provider's own mark in /integrations/ (Simple Icons or its site icon). */
  logo?: string;
  icon: IconName;
  /** Section on Apps & integrations. */
  group: string;
  blurb: string;
  codeReady: boolean;
  docAnchor: string;
  fields: ProviderField[];
  // google_calendar only: "Connect with Google" turns a saved client
  // id/secret into a refresh_token (kernel google_oauth.go).
  oauth?: boolean;
}

// One entry per provider INTEGRATIONS.md documents. codeReady ones have a
// real adapter in friday_common.integrations; the rest are stubs.
export const PROVIDERS: ProviderDescriptor[] = [
  {
    key: "paystack",
    label: "Paystack",
    logo: "/integrations/paystack.png",
    icon: "credit-card",
    group: "Get paid",
    blurb:
      "Card, M-Pesa and bank payments at the till and as invoice pay links, in your own Paystack account. Paystack signs its webhooks with this same secret key, so there's no separate webhook secret. Webhook URL (optional): your Friday address + /external/webhooks/paystack.",
    codeReady: true,
    docAnchor: "paystack",
    fields: [{ key: "secret_key", label: "Secret key", secret: true, placeholder: "sk_live_..." }],
  },
  {
    key: "pesapal",
    label: "Pesapal",
    logo: "/integrations/pesapal.ico",
    icon: "credit-card",
    group: "Get paid",
    blurb: "M-Pesa, Airtel and card checkout at the till.",
    codeReady: true,
    docAnchor: "pesapal",
    fields: [
      { key: "consumer_key", label: "Consumer key" },
      { key: "consumer_secret", label: "Consumer secret", secret: true },
    ],
  },
  {
    key: "stripe",
    label: "Stripe",
    logo: "/integrations/stripe.svg",
    icon: "credit-card",
    group: "Get paid",
    blurb: "Card payments on invoices.",
    codeReady: true,
    docAnchor: "stripe",
    fields: [
      { key: "secret_key", label: "Secret key", secret: true, placeholder: "sk_live_..." },
      { key: "webhook_secret", label: "Webhook secret", secret: true, placeholder: "whsec_..." },
    ],
  },
  {
    key: "guss",
    label: "Guss",
    icon: "sparkle",
    group: "Talk to customers",
    blurb: "Your shop assistant on WhatsApp and Telegram: sales, stock and expenses straight into Friday.",
    codeReady: true,
    docAnchor: "guss",
    fields: [
      { key: "url", label: "Guss address", placeholder: "https://shop-guss.tenants.fridayhost.dev" },
      { key: "token", label: "Web API token", secret: true, placeholder: "From Friday Host: Servers, Guss, Settings" },
    ],
  },
  {
    key: "slack",
    label: "Slack",
    logo: "/integrations/slack.svg",
    icon: "message-circle",
    group: "Talk to customers",
    blurb: "Post to a channel when a deal is won, an invoice is paid or stock runs low.",
    codeReady: true,
    docAnchor: "slack",
    fields: [{ key: "webhook_url", label: "Incoming webhook URL", placeholder: "https://hooks.slack.com/..." }],
  },
  {
    key: "resend",
    label: "Resend",
    logo: "/integrations/resend.svg",
    icon: "mail",
    group: "Talk to customers",
    blurb: "Email invoices and receipts to customers.",
    codeReady: true,
    docAnchor: "resend",
    fields: [
      { key: "api_key", label: "API key", secret: true, placeholder: "re_..." },
      { key: "from_email", label: "From address (optional)", placeholder: "Acme <billing@acme.com>" },
    ],
  },
  {
    key: "google_calendar",
    label: "Google Calendar",
    logo: "/integrations/google_calendar.svg",
    icon: "calendar",
    group: "Schedule",
    blurb: "Meetings from Friday land on everyone's calendar.",
    codeReady: true,
    docAnchor: "google-calendar",
    oauth: true,
    fields: [
      { key: "client_id", label: "Client ID" },
      { key: "client_secret", label: "Client secret", secret: true },
    ],
  },
  {
    key: "calendly",
    label: "Calendly",
    logo: "/integrations/calendly.svg",
    icon: "calendar",
    group: "Schedule",
    blurb: "Booking links.",
    codeReady: false,
    docAnchor: "calendly",
    fields: [{ key: "api_key", label: "Personal access token", secret: true }],
  },
  {
    key: "acyn_wallet",
    label: "Acyn Wallet",
    icon: "wallet",
    group: "Web3",
    blurb: "A business wallet for stablecoin payments and payouts.",
    codeReady: true,
    docAnchor: "acyn-wallet",
    fields: [{ key: "api_key", label: "Partner API key", secret: true, placeholder: "pk_live_..." }],
  },
  {
    key: "coingecko",
    label: "CoinGecko",
    logo: "/integrations/coingecko.png",
    icon: "trend-up",
    group: "Web3",
    blurb: "Crypto prices for the Web3 app. Works without a key.",
    codeReady: true,
    docAnchor: "coingecko",
    // The watchlist is edited from the Web3 Market page, not here.
    fields: [{ key: "api_key", label: "Pro API key (optional)", secret: true }],
  },
  {
    key: "bridge",
    label: "Bridge",
    logo: "/integrations/bridge.png",
    icon: "link-2",
    group: "Web3",
    blurb: "Move money between bank and stablecoins.",
    codeReady: false,
    docAnchor: "bridge",
    fields: [{ key: "api_key", label: "API key", secret: true }],
  },
  {
    key: "alchemy",
    label: "Alchemy",
    logo: "/integrations/alchemy.svg",
    icon: "link-2",
    group: "Web3",
    blurb: "Read balances and transactions on-chain.",
    codeReady: false,
    docAnchor: "alchemy",
    fields: [{ key: "api_key", label: "API key", secret: true }],
  },
  {
    key: "turnkey",
    label: "Turnkey",
    logo: "/integrations/turnkey.png",
    icon: "shield-check",
    group: "Web3",
    blurb: "Wallet key custody and signing.",
    codeReady: false,
    docAnchor: "turnkey",
    fields: [
      { key: "api_public_key", label: "API public key" },
      { key: "api_private_key", label: "API private key", secret: true },
      { key: "organization_id", label: "Organization ID" },
    ],
  },
  {
    key: "atlas",
    label: "MongoDB Atlas",
    logo: "/integrations/atlas.svg",
    icon: "database",
    group: "Data",
    blurb: "A managed database for forks that want one.",
    codeReady: false,
    docAnchor: "atlas",
    fields: [
      { key: "public_key", label: "Public key" },
      { key: "private_key", label: "Private key", secret: true },
      { key: "project_id", label: "Project ID" },
    ],
  },
];

/** An integration's settings: its fields, Save, Disconnect, and Google's
 * connect button. The stored config is fetched only here (admin-only
 * kernel route), and saving merges into it so keys this form doesn't
 * show (CoinGecko's watchlist) survive. */
export function ProviderEditor({
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
  const [values, setValues] = useState<Record<string, string>>({});
  const [rawConfig, setRawConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(connected && canManage);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!connected || !canManage) return;
    getIntegration(provider.key)
      .then((cred) => {
        setRawConfig(cred.config);
        setValues(Object.fromEntries(provider.fields.map((f) => [f.key, String(cred.config[f.key] ?? "")])));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the settings"))
      .finally(() => setLoading(false));
  }, [provider, connected, canManage]);

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await setIntegration(provider.key, { ...rawConfig, ...values });
      setNotice("Saved.");
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
      setValues({});
      setRawConfig({});
      setNotice("Disconnected.");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect");
    } finally {
      setSaving(false);
    }
  }

  const canConnectGoogle = Boolean(values.client_id?.trim() && values.client_secret?.trim());
  const googleConnected = Boolean(rawConfig.refresh_token);

  async function connectGoogle() {
    setConnecting(true);
    setError(null);
    try {
      await setIntegration(provider.key, { ...rawConfig, ...values });
      const { authorize_url } = await startGoogleCalendarOAuth();
      window.location.href = authorize_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start Google connect");
      setConnecting(false);
    }
  }

  if (!canManage) return <p className="field-label">Only owners and admins change integrations.</p>;
  if (loading) return <div className="spinner">Loading...</div>;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="field-label">{notice}</div> : null}
      {provider.fields.map((f) => (
        <FieldWrap key={f.key} label={f.label}>
          <Input
            type={f.secret ? "password" : "text"}
            autoComplete="off"
            placeholder={f.placeholder}
            value={values[f.key] ?? ""}
            onChange={(e) => setValues((cur) => ({ ...cur, [f.key]: e.target.value }))}
          />
        </FieldWrap>
      ))}
      {provider.oauth ? (
        <div className="field-label">
          {googleConnected
            ? "Connected to a Google Calendar account."
            : "Save the client ID and secret, then connect to get a refresh token."}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Button size="sm" variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving..." : connected ? "Save" : "Connect"}
        </Button>
        {provider.oauth ? (
          <Button size="sm" variant="primary" onClick={connectGoogle} disabled={saving || connecting || !canConnectGoogle}>
            {connecting ? "Connecting..." : googleConnected ? "Reconnect with Google" : "Connect with Google"}
          </Button>
        ) : null}
        {connected ? (
          <Button size="sm" variant="danger" onClick={disconnect} disabled={saving || connecting}>
            Disconnect
          </Button>
        ) : null}
      </div>
    </div>
  );
}
