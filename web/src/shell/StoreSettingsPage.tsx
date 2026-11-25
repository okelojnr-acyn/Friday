import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import {
  saveOrgSettings,
  useOrgSettings,
  type Storefront,
} from "../lib/orgSettings";
import { FieldWrap, Input, Select } from "../ui/Field";
import { SaveRow } from "./business/SaveRow";

// Same list as the kernel's org.StoreFonts.
const FONTS = [
  "Inter",
  "DM Sans",
  "Manrope",
  "Plus Jakarta Sans",
  "Work Sans",
  "Nunito",
  "Poppins",
  "Outfit",
  "Fraunces",
  "Playfair Display",
  "Lora",
  "DM Serif Display",
  "Space Grotesk",
  "Sora",
  "Lexend",
];

const DEFAULT_LOOK: Storefront = {
  store_name: "",
  tagline: "",
  logo_url: "",
  primary_color: "#1f2937",
  accent_color: "#f59e0b",
  background_color: "#ffffff",
  text_color: "#111827",
  heading_font: "DM Sans",
  body_font: "Inter",
  corners: "soft",
};

const COLORS = [
  ["primary_color", "Main colour", "Buttons, header"],
  ["accent_color", "Accent", "Prices, badges, links"],
  ["background_color", "Background", "Page"],
  ["text_color", "Text", "Body copy"],
] as const;

const RADIUS = { square: 0, soft: 10, round: 22 } as const;

/** Store settings: how the online store looks (name, logo, colours,
 * fonts, corners), with a live preview. The downloadable store kit
 * (STOREFRONT-PLAN.md, planned) carries these as its brand tokens. */
export function StoreSettingsPage() {
  const { session } = useAuth();
  const canEdit = session?.role === "owner" || session?.role === "admin";
  const settings = useOrgSettings();
  const [look, setLook] = useState<Storefront>(
    settings.storefront ?? DEFAULT_LOOK,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const oldKernel = !settings.storefront && settings.name !== "";

  useEffect(() => {
    if (settings.storefront) setLook(settings.storefront);
  }, [settings.storefront]);

  // Load the two chosen fonts for the preview.
  useEffect(() => {
    const families = [...new Set([look.heading_font, look.body_font])]
      .map((f) => `family=${encodeURIComponent(f)}:wght@400;600;700`)
      .join("&");
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?${families}&display=swap`;
    document.head.appendChild(link);
    return () => link.remove();
  }, [look.heading_font, look.body_font]);

  const set = <K extends keyof Storefront>(key: K, value: Storefront[K]) => {
    setSaved(false);
    setLook((l) => ({ ...l, [key]: value }));
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveOrgSettings({ storefront: look });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  const name = look.store_name || settings.name || "Your store";
  const radius = RADIUS[look.corners];

  return (
    <div className="page" style={{ maxWidth: 1100 }}>
      <div className="page-header">
        <h1 className="page-title">Store settings</h1>
        <span className="field-label">How your online store looks</span>
      </div>
      {oldKernel ? (
        <div className="error-banner">
          Update Friday in Friday Host to save store settings.
        </div>
      ) : null}
      {error ? <div className="error-banner">{error}</div> : null}

      <div
        style={{
          display: "grid",
          gap: 16,
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          alignItems: "start",
        }}
      >
        <div className="card card-padded form-grid">
          <FieldWrap label="Store name">
            <Input
              value={look.store_name}
              maxLength={60}
              placeholder={settings.name}
              disabled={!canEdit}
              onChange={(e) => set("store_name", e.target.value)}
            />
          </FieldWrap>
          <FieldWrap label="Tagline">
            <Input
              value={look.tagline}
              maxLength={120}
              placeholder="Fresh groceries, delivered"
              disabled={!canEdit}
              onChange={(e) => set("tagline", e.target.value)}
            />
          </FieldWrap>
          <FieldWrap label="Logo link (https://)">
            <Input
              value={look.logo_url}
              maxLength={500}
              placeholder="https://…/logo.png"
              disabled={!canEdit}
              onChange={(e) => set("logo_url", e.target.value)}
            />
          </FieldWrap>
          {COLORS.map(([key, label, hint]) => (
            <FieldWrap key={key} label={`${label} · ${hint}`}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="color"
                  aria-label={label}
                  value={look[key]}
                  disabled={!canEdit}
                  onChange={(e) => set(key, e.target.value)}
                  style={{
                    width: 44,
                    height: 36,
                    padding: 0,
                    border: "none",
                    background: "none",
                  }}
                />
                <Input
                  value={look[key]}
                  maxLength={7}
                  disabled={!canEdit}
                  aria-label={`${label} hex code`}
                  onChange={(e) => set(key, e.target.value)}
                />
              </div>
            </FieldWrap>
          ))}
          <FieldWrap label="Heading font">
            <Select
              value={look.heading_font}
              disabled={!canEdit}
              onChange={(e) => set("heading_font", e.target.value)}
            >
              {FONTS.map((f) => (
                <option key={f}>{f}</option>
              ))}
            </Select>
          </FieldWrap>
          <FieldWrap label="Body font">
            <Select
              value={look.body_font}
              disabled={!canEdit}
              onChange={(e) => set("body_font", e.target.value)}
            >
              {FONTS.map((f) => (
                <option key={f}>{f}</option>
              ))}
            </Select>
          </FieldWrap>
          <FieldWrap label="Corners">
            <Select
              value={look.corners}
              disabled={!canEdit}
              onChange={(e) =>
                set("corners", e.target.value as Storefront["corners"])
              }
            >
              <option value="square">Square</option>
              <option value="soft">Soft</option>
              <option value="round">Round</option>
            </Select>
          </FieldWrap>
          <SaveRow
            canEdit={canEdit && !oldKernel}
            saving={saving}
            onSave={save}
          />
          {saved ? <span className="field-label">Saved.</span> : null}
        </div>

        <div
          className="card"
          aria-label="Preview"
          style={{ overflow: "hidden", position: "sticky", top: 16 }}
        >
          <div
            style={{
              background: look.background_color,
              color: look.text_color,
              fontFamily: `"${look.body_font}", sans-serif`,
            }}
          >
            <div
              style={{
                background: look.primary_color,
                color: "#fff",
                padding: "14px 18px",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              {look.logo_url.startsWith("https://") ? (
                <img
                  src={look.logo_url}
                  alt=""
                  style={{ height: 28, maxWidth: 120, objectFit: "contain" }}
                />
              ) : null}
              <strong
                style={{
                  fontFamily: `"${look.heading_font}", serif`,
                  fontSize: 18,
                }}
              >
                {name}
              </strong>
              <span style={{ marginLeft: "auto", fontSize: 13, opacity: 0.85 }}>
                Cart (2)
              </span>
            </div>
            <div style={{ padding: 18 }}>
              <h2
                style={{
                  fontFamily: `"${look.heading_font}", serif`,
                  margin: "0 0 4px",
                  fontSize: 26,
                }}
              >
                {name}
              </h2>
              <p style={{ margin: "0 0 16px", opacity: 0.75 }}>
                {look.tagline || "Your tagline shows here"}
              </p>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 12,
                }}
              >
                {["Sugar 2kg", "Cooking oil 1L"].map((item, i) => (
                  <div
                    key={item}
                    style={{
                      border: `1px solid ${look.text_color}22`,
                      borderRadius: radius,
                      padding: 12,
                    }}
                  >
                    <div
                      style={{
                        height: 64,
                        borderRadius: radius,
                        background: `${look.primary_color}14`,
                        marginBottom: 8,
                      }}
                    />
                    <div style={{ fontWeight: 600 }}>{item}</div>
                    <div style={{ color: look.accent_color, fontWeight: 700 }}>
                      {settings.currency} {i ? "420" : "380"}
                    </div>
                    <button
                      type="button"
                      tabIndex={-1}
                      style={{
                        marginTop: 8,
                        width: "100%",
                        border: "none",
                        borderRadius: radius,
                        padding: "8px 0",
                        background: look.primary_color,
                        color: "#fff",
                        fontFamily: "inherit",
                        fontWeight: 600,
                      }}
                    >
                      Add to cart
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
      <p className="field-label" style={{ marginTop: 16, maxWidth: "70ch" }}>
        Coming next: download your store as a ready-made kit (these colours and
        fonts included) and hand it to an AI coder such as Claude Code to build
        and publish it.
      </p>
    </div>
  );
}
