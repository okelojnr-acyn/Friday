#!/bin/sh
# Every night (cron, 00:00 Nairobi): the demo goes back to golden.dump.
set -eu
cd /opt/friday-demo
dc() { docker compose -p friday-demo -f compose.yml -f compose.demo.yml --env-file .env "$@"; }
APPS="kernel crm invoicing projects inventory web3 accounting minions fleets"
dc stop $APPS
dc exec -T postgres pg_restore -U friday -d friday --clean --if-exists --no-owner < golden.dump
dc start $APPS
echo "$(date -u +%FT%TZ) demo reset"
