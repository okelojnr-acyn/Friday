import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import MinionsApp from "./minions/MinionsApp";
import "./ui/tokens.css";
import "./ui/components.css";

// Registered only here, never from main.tsx -- the service worker and
// manifest are a Minions-only concern. The main shell's index.html has
// no <link rel="manifest">, so even though the build emits one
// manifest/sw.js pair, the admin shell never references or installs it.
registerSW({ immediate: true });

// MinionsApp's routes assume they own "/" -- true once this is served
// from its own subdomain (the intended deployment), but *not* true
// visiting this same build's /minions.html directly. Same bug
// web/src/pos-main.tsx's own basename fix closed this session (found by
// an actual browser test: the router's wildcard route rewrote the URL
// from /pos.html to /, which looks harmless until the next reload
// serves index.html -- the main shell -- instead, silently dropping the
// mini-app). Minions had the identical unmodified pattern; this is the
// same fix, not a new one.
const basename = window.location.pathname.startsWith("/minions.html") ? "/minions.html" : "/";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <MinionsApp />
    </BrowserRouter>
  </StrictMode>,
);
