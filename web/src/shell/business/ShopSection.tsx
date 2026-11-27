import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { KERNEL_URL } from "../../lib/runtimeConfig";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";

type ShopKey = { id: string; name: string; key: string; origins: string[]; created_at: string };

/** Business settings > Online shop: keys an online shop's pages use to
 * read the catalogue (kernel internal/shop). A key is public by design:
 * it only reads names, prices, photos and what's in stock. */
export function ShopSection({ canEdit }: { canEdit: boolean }) {
  const [keys, setKeys] = useState<ShopKey[] | null>(null);
  const [sites, setSites] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api
      .get<ShopKey[]>("/orgs/shop-keys")
      .then((ks) => {
        setKeys(ks);
        // The business website's address (Friday Host made its key) comes filled in.
        setSites((now) => now || ks.find((k) => k.origins.length)?.origins.join(", ") || "");
      })
      .catch((err) =>
        setError(err instanceof ApiError && err.status === 404 ? "Update Friday to use an online shop." : "Could not load the shop keys."),
      );
  }
  useEffect(() => {
    if (canEdit) load();
  }, [canEdit]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) return <p className="field-label">Owners and admins manage the online shop.</p>;

  const catalogURL = (k: ShopKey) => `${KERNEL_URL}/public/catalog?key=${k.key}`;
  // What a shop built elsewhere (Lovable, Vercel, Claude Code) needs, ready to paste.
  const settingsFor = (k: ShopKey) => `FRIDAY_API_URL=${KERNEL_URL}\nFRIDAY_SHOP_KEY=${k.key}`;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <p className="field-label">
        Your online shop reads what you sell from Friday with a shop key: names, prices, photos and what&apos;s in
        stock, never costs or quantities. Products with a price and &quot;Sell in the online shop&quot; ticked (Inventory) are listed; orders arrive in Inventory, Online orders.
      </p>
      {keys?.map((k) => (
        <div key={k.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12 }}>
          <div className="field-label">{k.name}</div>
          <p style={{ fontFamily: "monospace", wordBreak: "break-all", margin: "4px 0" }}>{k.key}</p>
          <p className="field-label" style={{ margin: "0 0 8px" }}>
            {k.origins.length ? `Only on ${k.origins.join(", ")}` : "Any website can use it"}
          </p>
          <pre style={{ margin: "0 0 8px", padding: 8, background: "var(--surface-2, rgba(0,0,0,.04))", borderRadius: 6, whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 13 }}>
            {settingsFor(k)}
          </pre>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button size="sm" variant="secondary" onClick={() => window.open(catalogURL(k), "_blank", "noopener")}>
              See the catalogue
            </Button>
            <Button size="sm" variant="secondary" onClick={() => navigator.clipboard?.writeText(settingsFor(k)).catch(() => {})}>
              Copy settings
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => run(() => api.del(`/orgs/shop-keys/${k.id}`))}>
              Revoke
            </Button>
          </div>
        </div>
      ))}
      {keys && keys.length === 0 ? <p className="field-label">No shop keys yet.</p> : null}
      <FieldWrap label="Websites allowed to use a new key (optional, comma separated)">
        <Input value={sites} placeholder="https://shop.example.com" onChange={(e) => setSites(e.target.value)} />
      </FieldWrap>
      <div>
        <Button
          disabled={busy}
          onClick={() =>
            run(async () => {
              await api.post("/orgs/shop-keys", {
                name: "Online shop",
                origins: sites.split(",").map((s) => s.trim()).filter(Boolean),
              });
              setSites("");
            })
          }
        >
          {busy ? "Making…" : "Make a shop key"}
        </Button>
      </div>
      {error ? (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
