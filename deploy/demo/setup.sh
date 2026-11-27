#!/bin/sh
# First run on the box: makes /opt/friday-demo, writes its .env with fresh
# secrets (never printed), starts the stack. Usage: setup.sh <release sha>
set -eu
VERSION="${1:?release sha}"
DIR=/opt/friday-demo
SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/firewall" "$DIR/sites"
cp "$SRC/../compose.yml" "$SRC/../Caddyfile" "$SRC/compose.demo.yml" "$SRC/seed.py" "$SRC/seed.sh" "$SRC/reset.sh" "$DIR/"
cd "$DIR"
if [ ! -f .env ]; then
  umask 077
  r() { openssl rand -base64 32 | tr -d '\n'; }
  {
    echo "FRIDAY_VERSION=$VERSION"
    echo "FRIDAY_DOMAIN=demo.fridayhost.dev"
    echo "FRIDAY_NAME=Friday demo"
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "JWT_SECRET=$(r)"
    echo "KERNEL_EVENTS_TOKEN=$(openssl rand -hex 24)"
    echo "FRIDAY_SECRETS_KEY=$(r)"
  } > .env
else
  sed -i "s/^FRIDAY_VERSION=.*/FRIDAY_VERSION=$VERSION/" .env
fi
dc() { docker compose -p friday-demo -f compose.yml -f compose.demo.yml --env-file .env "$@"; }
dc pull -q
dc up -d --remove-orphans
echo "started; next: $DIR/seed.sh"
