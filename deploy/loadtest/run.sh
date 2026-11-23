#!/usr/bin/env bash
# Load, failure and soak test of a released Friday (Friday Host
# RELIABILITY-PLAN phase D). Runs deploy/compose.yml with the Friday Host
# overrides in compose.load.yml, then:
#   1. load at each multiple in MULTS (1 = the busy-organisation model);
#   2. checks nothing was lost: every sale the till was told was recorded
#      is stored, moved stock and reached the books; every event delivered;
#   3. failure drills under load: an app restarts, Postgres stops for 20 s;
#   4. a soak at 1x for SOAK_MIN minutes and the memory drift over it.
# Results (k6 summaries, docker stats, slow queries, summary.md) go to
# loadtest/results. Exits non-zero when 1x misses its service levels,
# anything is lost, a drill doesn't recover, or memory grows > 50%.
#
#   FRIDAY_VERSION=<released commit> deploy/loadtest/run.sh
#   env: MULTS="1 2 5" DURATION=5m SOAK_MIN=30 DRILLS=1
set -uo pipefail
cd "$(dirname "$0")/.."
: "${FRIDAY_VERSION:?set FRIDAY_VERSION to a released commit}"
MULTS=${MULTS:-"1 2 5"}
DURATION=${DURATION:-5m}
SOAK_MIN=${SOAK_MIN:-30}
DRILLS=${DRILLS:-1}
K6_IMAGE=grafana/k6:0.54.0
R=loadtest/results
rm -rf "$R" && mkdir -p "$R" && chmod 777 "$R" # k6 writes here as its own user
# Appends to failures.txt (works from subshells too); any line fails the run.
fail() { echo "FAIL: $*" | tee -a "$R/failures.txt"; }

TENANT_PW=$(openssl rand -hex 16)
{
  echo "FRIDAY_VERSION=$FRIDAY_VERSION"
  echo "FRIDAY_DOMAIN=localhost"
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
  echo "JWT_SECRET=$(openssl rand -hex 32)"
  echo "KERNEL_EVENTS_TOKEN=$(openssl rand -hex 32)"
  echo "FRIDAY_DATABASE_URL=postgres://tenant:$TENANT_PW@pgbouncer:6432/tenant?sslmode=disable"
} > .env
printf '"tenant" "%s"\n' "$TENANT_PW" > loadtest/userlist.txt
DC=(docker compose -f compose.yml -f loadtest/compose.load.yml --env-file .env)
sql() { "${DC[@]}" exec -T postgres psql -U friday -d "${2:-tenant}" -Atc "$1"; }

healthy() {
  local bad
  for _ in $(seq 1 60); do
    bad=$("${DC[@]}" ps --format '{{.Service}} {{.Health}}' | awk '$2 != "" && $2 != "healthy"')
    [ -z "$bad" ] && return 0
    sleep 5
  done
  echo "not healthy: $bad"
  return 1
}

# --- The stack, as Friday Host runs it -------------------------------------
"${DC[@]}" up -d postgres
for _ in $(seq 1 30); do sql "SELECT 1" friday >/dev/null 2>&1 && break; sleep 2; done
"${DC[@]}" exec -T postgres psql -U friday -d friday -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE tenant LOGIN PASSWORD '$TENANT_PW' CONNECTION LIMIT 20;
ALTER ROLE tenant SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE tenant SET statement_timeout = '120s';
CREATE DATABASE tenant OWNER tenant;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
"${DC[@]}" up -d
healthy || { "${DC[@]}" logs --tail 80; exit 1; }
for _ in $(seq 1 30); do curl -skf https://localhost/kernel/healthz >/dev/null && break; sleep 2; done

"${DC[@]}" exec -T kernel ./kernel bootstrap "Load Shop" load@example.com >/dev/null
ORG=$(sql "SELECT m.org_id FROM core.memberships m JOIN core.users u ON u.id = m.user_id WHERE lower(u.email) = 'load@example.com'")
[[ "$ORG" =~ ^[0-9a-f-]{36}$ ]] || { echo "no organisation (got '$ORG')"; exit 1; }
# An owner's sign-in token, signed with this run's JWT_SECRET (owners act
# by their role, so no permissions list is needed); valid three hours.
b64() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
JWT_SECRET=$(sed -n 's/^JWT_SECRET=//p' .env)
OWNER=$(sql "SELECT id FROM core.users WHERE lower(email) = 'load@example.com'")
NOW=$(date +%s)
HEADER=$(printf '{"alg":"HS256","typ":"JWT"}' | b64)
CLAIMS=$(printf '{"sub":"%s","org_id":"%s","role":"owner","email":"load@example.com","iat":%d,"exp":%d}' "$OWNER" "$ORG" "$NOW" $((NOW + 10800)) | b64)
TOKEN="$HEADER.$CLAIMS.$(printf '%s.%s' "$HEADER" "$CLAIMS" | openssl dgst -sha256 -hmac "$JWT_SECRET" -binary | b64)"
[ ${#TOKEN} -gt 100 ] || { echo "no token"; exit 1; }
for app in inventory invoicing accounting; do
  curl -sk -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" "https://localhost/kernel/orgs/apps/$app/install"
done

# Memory and CPU of every container every 15 s, for the whole run.
( while :; do
    docker stats --no-stream --format "$(date +%s),{{.Name}},{{.MemUsage}},{{.CPUPerc}}"
    sleep 15
  done ) > "$R/stats.csv" 2>/dev/null &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

k6run() { # multiple duration label
  docker run --rm --network host -v "$PWD/loadtest:/lt" \
    -e BASE=https://localhost/kernel -e TOKEN="$TOKEN" -e MULT="$1" -e DURATION="$2" \
    "$K6_IMAGE" run --quiet --summary-export="/lt/results/k6-$3.json" /lt/friday.js > "$R/k6-$3.log" 2>&1
}

OUTBOXES="crm invoicing projects inventory web3 accounting minions fleets"
undelivered() {
  local q="SELECT count(*) FROM core.event_deliveries WHERE delivered_at IS NULL"
  for s in $OUTBOXES; do q="$q UNION ALL SELECT count(*) FROM $s.event_outbox WHERE delivered_at IS NULL"; done
  sql "SELECT sum(count) FROM ($q) t"
}
drained() {
  for _ in $(seq 1 72); do [ "$(undelivered)" = "0" ] && return 0; sleep 5; done
  return 1
}

# Every sale the till was told was recorded is stored, moved stock and was booked.
consistent() { # label expected-sales
  local stored moved booked
  stored=$(sql "SELECT count(*) FROM invoicing.invoices WHERE source = 'pos' AND status = 'paid'")
  moved=$(sql "SELECT count(DISTINCT reference) FROM inventory.stock_moves WHERE reference IN (SELECT number FROM invoicing.invoices WHERE source = 'pos')")
  booked=$(sql "SELECT count(DISTINCT source_ref) FROM accounting.journal_entries WHERE source_ref IN (SELECT number FROM invoicing.invoices WHERE source = 'pos' UNION SELECT id::text FROM invoicing.invoices WHERE source = 'pos')")
  echo "$1: till told recorded $2, stored $stored, stock moved $moved, booked $booked" | tee -a "$R/consistency.txt"
  [ "$stored" -ge "$2" ] || fail "$1: $(( $2 - stored )) recorded sales missing"
  [ "$moved" = "$stored" ] || fail "$1: $(( stored - moved )) sales without stock moves"
  [ "$booked" = "$stored" ] || fail "$1: $(( stored - booked )) sales not in the books"
}
recorded() { # total sales_recorded over the given k6 summaries
  local n=0 c
  for f in "$@"; do c=$(jq -r '.metrics.sales_recorded.count // 0' "$f" 2>/dev/null || echo 0); n=$(( n + ${c%.*} )); done
  echo "$n"
}

# --- 1. Load at each multiple ---------------------------------------------
for m in $MULTS; do
  echo "== load ${m}x for $DURATION"
  k6run "$m" "$DURATION" "load-${m}x"
  code=$?
  [ "$m" = "1" ] && [ $code -ne 0 ] && fail "1x load missed its service levels (see k6-load-1x.log)"
  drained || fail "events still undelivered 6 minutes after ${m}x"
done
consistent "after load" "$(recorded "$R"/k6-load-*.json)"

# --- 2. Failure drills under load ------------------------------------------
if [ "$DRILLS" = "1" ]; then
  echo "== drills"
  k6run 1 4m drills & K6=$!
  sleep 40; "${DC[@]}" restart invoicing
  sleep 60; "${DC[@]}" stop postgres; sleep 20; "${DC[@]}" start postgres
  wait $K6
  healthy || fail "services not healthy 5 minutes after the drills"
  drained || fail "events not delivered after the drills"
  consistent "after drills" "$(recorded "$R"/k6-load-*.json "$R"/k6-drills.json)"
  for c in $("${DC[@]}" ps -q); do
    [ "$(docker inspect -f '{{.State.OOMKilled}}' "$c")" = "true" ] && fail "$(docker inspect -f '{{.Name}}' "$c") was killed for memory"
  done
fi

# --- 3. Soak ----------------------------------------------------------------
if [ "$SOAK_MIN" -gt 0 ]; then
  echo "== soak 1x for ${SOAK_MIN}m"
  SOAK_FROM=$(date +%s)
  k6run 1 "${SOAK_MIN}m" soak || fail "soak missed its service levels (see k6-soak.log)"
  SOAK_TO=$(date +%s)
  # MiB per container: average of the soak's first 5 minutes vs its last 5.
  awk -F, -v from="$SOAK_FROM" -v to="$SOAK_TO" '
    function mib(s,  n, u) { n = s + 0; u = s; sub(/^[0-9.]+/, "", u)
      return u ~ /^GiB/ ? n * 1024 : u ~ /^KiB/ ? n / 1024 : u ~ /^B/ ? n / 1048576 : n }
    $1 >= from && $1 <= to { split($3, m, " / "); v = mib(m[1])
      if ($1 < from + 300) { a[$2] += v; na[$2]++ } else if ($1 > to - 300) { b[$2] += v; nb[$2]++ } }
    END { for (c in a) if (nb[c]) { s = a[c] / na[c]; e = b[c] / nb[c]
      printf "%s %.0f %.0f %+.0f%%\n", c, s, e, (e - s) * 100 / (s > 1 ? s : 1) } }' "$R/stats.csv" | sort > "$R/drift.txt"
  awk '{ gsub(/[+%]/, "", $4); if ($4 + 0 > 50 && $3 > 32) print }' "$R/drift.txt" | while read -r c s e d; do
    fail "memory of $c grew from ${s} to ${e} MiB during the soak"
  done
  drained || fail "events not delivered after the soak"
fi

# --- Findings ---------------------------------------------------------------
sql "SELECT round(mean_exec_time::numeric, 1) || ' ms x ' || calls || ': ' || left(regexp_replace(query, '\s+', ' ', 'g'), 160)
     FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'tenant')
     ORDER BY total_exec_time DESC LIMIT 15" friday > "$R/slow-queries.txt"
"${DC[@]}" logs postgres 2>&1 | grep -c "duration:" > "$R/slow-log-count.txt" || true
for s in kernel crm invoicing projects inventory web3 accounting minions fleets pgbouncer; do
  printf '%s %s\n' "$s" "$("${DC[@]}" logs "$s" 2>&1 | grep -ciE 'error|traceback|panic')"
done > "$R/error-lines.txt"
# What the errors were: each distinct line (timestamps and ids stripped), most frequent first.
for s in kernel invoicing inventory accounting pgbouncer; do
  "${DC[@]}" logs --no-log-prefix "$s" 2>&1 | grep -iE 'error|exception|panic' \
    | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.]+( UTC)?//g; s/[0-9a-f]{8}-[0-9a-f-]{27}/<id>/g; s/0x[0-9a-f]+/<p>/g; s/[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+/<addr>/g' \
    | sort | uniq -c | sort -rn | head -15 > "$R/errors-$s.txt"
done

{
  echo "## Friday load test ($FRIDAY_VERSION)"
  echo
  echo "| Run | Till sale p95 | Staff page p95 | Catalogue p95 | Failed requests | Sales recorded |"
  echo "|---|---|---|---|---|---|"
  for f in "$R"/k6-*.json; do
    jq -r --arg run "$(basename "$f" .json | sed 's/^k6-//')" '
      def p95(k): (.metrics[k]["p(95)"] // 0 | floor | tostring) + " ms";
      "| \($run) | \(p95("http_req_duration{scenario:tills}")) | \(p95("http_req_duration{scenario:staff}")) | \(p95("http_req_duration{scenario:shoppers}")) | \((.metrics.http_req_failed.value // 0) * 100 | . * 100 | floor / 100)% | \(.metrics.sales_recorded.count // 0) |"' "$f"
  done
  echo
  echo "**Consistency**"; echo '```'; cat "$R/consistency.txt" 2>/dev/null; echo '```'
  echo "**Memory drift over the soak (MiB: first 5 min, last 5 min)**"; echo '```'; cat "$R/drift.txt" 2>/dev/null; echo '```'
  echo "**Slowest statements (total time)**"; echo '```'; cat "$R/slow-queries.txt"; echo '```'
  echo "**Error lines in logs**"; echo '```'; cat "$R/error-lines.txt"; echo '```'
  echo "**Failures**"; echo '```'; cat "$R/failures.txt" 2>/dev/null || echo none; echo '```'
} > "$R/summary.md"
cat "$R/summary.md"
[ ! -s "$R/failures.txt" ]
