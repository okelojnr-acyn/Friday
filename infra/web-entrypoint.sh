#!/bin/sh
# Writes the runtime config the SPA reads (web/src/lib/runtimeConfig.ts),
# then serves the app.
set -eu
: "${FRIDAY_KERNEL_URL:?set FRIDAY_KERNEL_URL, e.g. https://shop.example.com/kernel}"
case "$FRIDAY_KERNEL_URL" in
  *'"'* | *'\'* | *'<'*)
    echo "FRIDAY_KERNEL_URL must not contain quotes, backslashes or <" >&2
    exit 1
    ;;
esac
printf 'window.__FRIDAY__ = { kernelUrl: "%s" };\n' "$FRIDAY_KERNEL_URL" > /srv/config.js
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
