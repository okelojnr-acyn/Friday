#!/bin/sh
# Every 10 minutes (cron): the demo follows the shared Friday's release,
# the one the owner's Update button moves. Quiet when nothing changed.
set -eu
cd /opt/friday-demo
SHARED=$(docker ps --format '{{.Names}} {{.Image}}' | awk '$1 !~ /^friday-demo-/ && $2 ~ /friday-kernel:/ {split($2, a, ":"); print a[2]; exit}')
CURRENT=$(sed -n 's/^FRIDAY_VERSION=//p' .env)
[ -n "$SHARED" ] && [ "$SHARED" != "$CURRENT" ] || exit 0
SRC=$(mktemp -d)
curl -fsSL "https://codeload.github.com/okelojnr-acyn/Friday/tar.gz/$SHARED" | tar -xz -C "$SRC" --strip-components=1 \
  --wildcards '*/deploy/compose.yml' '*/deploy/Caddyfile' '*/deploy/demo/*'
sh "$SRC/deploy/demo/setup.sh" "$SHARED"
rm -rf "$SRC"
echo "$(date -u +%FT%TZ) demo now on $SHARED"
