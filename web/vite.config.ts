import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// pos-engine's wasm-pack output lands in src/apps/pos/engine (see
// scripts/setup.sh / README.md), imported by relative path -- Vite
// handles the .wasm asset and the generated JS glue natively, no plugin
// needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
