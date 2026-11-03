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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <MinionsApp />
    </BrowserRouter>
  </StrictMode>,
);
