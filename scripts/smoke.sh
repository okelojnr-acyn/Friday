#!/bin/sh
# Post-deploy smoke check for a live Friday install. Hits the kernel's
# install-wide GET /health (kernel DB + every app's real-query /health)
# and fails loudly if anything is down. Run after every update:
#
#   scripts/smoke.sh https://friday-api.fridayhost.dev
#
# Exit 0 = every component healthy; 1 = something isn't (details printed);
# 2 = kernel unreachable / not a Friday kernel.
set -u
KERNEL_URL="${1:?usage: scripts/smoke.sh <kernel base URL>}"
BODY=$(curl -sS --max-time 20 -w '\n%{http_code}' "${KERNEL_URL%/}/health") || { echo "FAIL: kernel unreachable at $KERNEL_URL"; exit 2; }
CODE=$(printf '%s' "$BODY" | tail -n1)
JSON=$(printf '%s' "$BODY" | sed '$d')

case "$JSON" in
  *'"apps"'*) ;;
  *) echo "FAIL: $KERNEL_URL/health is not a Friday kernel health report (HTTP $CODE)"; exit 2 ;;
esac

# One line per component, no jq dependency.
printf '%s' "$JSON" | tr '{},' '\n\n\n' | grep -E '"(status|error)"|":$|^"[a-z0-9_]+":' | sed 's/^/  /'
if [ "$CODE" = "200" ]; then
  echo "OK: all components healthy"
  exit 0
fi
echo "FAIL: HTTP $CODE -- see components above"
exit 1
