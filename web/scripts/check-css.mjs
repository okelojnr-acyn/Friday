// Every block in every stylesheet is closed. An unclosed one silently
// nests every later rule (CSS nesting): .minions-notice's missing "}" hid
// the demo banner, the calendar and the spending presets' styles for days.
// Run by CI (web job); `node scripts/check-css.mjs` locally.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const files = (dir) =>
  readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p) : p.endsWith(".css") ? [p] : [];
  });

let bad = 0;
for (const f of files(new URL("../src", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"))) {
  let depth = 0;
  let line = 1;
  for (const ch of readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ""))) {
    if (ch === "\n") line++;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth < 0) break;
  }
  if (depth !== 0) {
    console.error(`${f}: ${depth > 0 ? "an unclosed block" : "a stray }"} (near line ${line})`);
    bad++;
  }
}
if (bad) process.exit(1);
console.log("stylesheets: every block closed");
