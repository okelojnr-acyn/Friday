import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import PosApp from "./apps/pos/PosApp";
import "./ui/tokens.css";
import "./ui/components.css";

// Hand-registered, not VitePWA's registerSW() helper -- see
// vite.config.ts's comment on why POS doesn't get a second VitePWA()
// instance. The explicit `scope` is what keeps this from ever
// controlling the main shell or Minions, even served from one origin:
// a service worker's scope can be narrower than what its own script
// location would allow by default, just never wider.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/pos-sw.js", { scope: "/pos.html" });
}

// PosApp's routes assume they own "/" -- true once this is served from
// its own subdomain (the eventual deployment, matching Minions' same
// aspiration), but *not* true visiting this same build's /pos.html
// directly (today's reality, confirmed by an actual browser test: the
// router's own wildcard route rewrote the URL from /pos.html to /,
// which looks harmless until the next reload serves index.html -- the
// main shell -- instead, silently dropping the POS app entirely). This
// adapts to whichever is true at load time rather than hardcoding one.
const basename = window.location.pathname.startsWith("/pos.html") ? "/pos.html" : "/";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <PosApp />
    </BrowserRouter>
  </StrictMode>,
);
