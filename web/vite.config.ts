import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// VitePWA injects <link rel="manifest"> into every HTML entry it
// processes, regardless of injectRegister -- which would otherwise leak
// Minions' manifest (wrong name/icon) into the main shell's index.html.
// Rather than rely on however the plugin happens to behave (which
// differs between `vite dev` and `vite build`), this strips every
// auto-injected manifest link unconditionally and re-adds exactly one,
// by hand, only for minions.html -- deterministic in both modes. Also
// hand-adds POS's own manifest link to pos.html -- that one is a static
// file (public/pos-manifest.webmanifest), not VitePWA-generated at all
// (see the VitePWA call below for why: a second instance isn't safe),
// so there's nothing to strip for it, only to add.
// Registered after VitePWA in the plugins array below: both plugins'
// transformIndexHtml hooks use order "post", and hooks with equal order
// run in plugins-array position, so this one needs to run second to
// have something to strip.
function manageManifestLink(): Plugin {
  return {
    name: "manage-pwa-manifest-link",
    enforce: "post",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        const stripped = html.replace(/<link rel="manifest"[^>]*>\s*/g, "");
        if (ctx.filename.endsWith("minions.html")) {
          return stripped.replace("</head>", '    <link rel="manifest" href="/manifest.webmanifest" />\n  </head>');
        }
        if (ctx.filename.endsWith("pos.html")) {
          return stripped.replace(
            "</head>",
            '    <link rel="manifest" href="/pos-manifest.webmanifest" />\n  </head>',
          );
        }
        return stripped;
      },
    },
  };
}

// pos-engine's wasm-pack output lands in src/apps/pos/engine (see
// scripts/setup.sh / README.md), imported by relative path -- Vite
// handles the .wasm asset and the generated JS glue natively, no plugin
// needed.
export default defineConfig({
  plugins: [
    react(),
    // VitePWA generates manifest.webmanifest + sw.js once for the whole
    // build, but injectRegister is null so it never adds a registration
    // script to either HTML entry on its own -- only
    // src/minions-main.tsx calls registerSW(). The main shell
    // (index.html) never calls it, so it never registers a service
    // worker from its own code. Note this only isolates the two apps
    // when they're deployed to separate origins (per the plan, Minions
    // gets its own subdomain) -- serving both from one origin, a
    // service worker registered with the default root scope would still
    // control every page on that origin, Minions or not. That's the one
    // real tradeoff of shipping Minions as a second entry in this same
    // package rather than a fully separate project.
    //
    // POS (pos.html/pos-main.tsx) deliberately does NOT get a second
    // VitePWA() instance here -- confirmed by reading the plugin's own
    // source (node_modules/vite-plugin-pwa/dist/chunk-*.js) that
    // `virtual:pwa-register` is one fixed global module name with no
    // per-instance scoping, so a second instance would race this one
    // over which wins that import, silently registering the wrong
    // service worker for whichever page imports it. POS instead has a
    // hand-written public/pos-sw.js + public/pos-manifest.webmanifest,
    // registered with an explicit narrow scope (see pos-main.tsx) --
    // avoids the collision entirely rather than hoping it doesn't happen.
    VitePWA({
      injectRegister: null,
      registerType: "autoUpdate",
      manifest: {
        name: "Friday Minions",
        short_name: "Minions",
        description: "My Tasks, Expense Claims, Payroll, and Wallet -- the employee side of Friday.",
        theme_color: "#e07a35",
        background_color: "#ffffff",
        display: "standalone",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "/minions-icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/minions-icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
    manageManifestLink(),
  ],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        minions: "minions.html",
        pos: "pos.html",
      },
    },
  },
  server: {
    port: 5173,
  },
});
