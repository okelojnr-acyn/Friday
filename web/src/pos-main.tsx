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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <PosApp />
    </BrowserRouter>
  </StrictMode>,
);
