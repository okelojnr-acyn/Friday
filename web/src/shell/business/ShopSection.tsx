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
      .then(setKeys)
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
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <p className="field-label">
        Your online shop reads what you sell from Friday with a shop key: names, prices, photos and what&apos;s in
        stock, never costs or quantities. Every product with a price is listed.
      </p>
      {keys?.map((k) => (
        <div key={k.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12 }}>
          <div className="field-label">{k.name}</div>
          <p style={{ fontFamily: "monospace", wordBreak: "break-all", margin: "4px 0" }}>{k.key}</p>
          <p className="field-label" style={{ margin: "0 0 8px" }}>
            {k.origins.length ? `Only on ${k.origins.join(", ")}` : "Any website can use it"}
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button size="sm" variant="secondary" onClick={() => window.open(catalogURL(k), "_blank", "noopener")}>
              See the catalogue
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
