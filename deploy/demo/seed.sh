#!/bin/sh
# Makes the demo business and its sample data, then keeps a copy of the
# database (golden.dump) that reset.sh goes back to every night.
set -eu
cd /opt/friday-demo
dc() { docker compose -p friday-demo -f compose.yml -f compose.demo.yml --env-file .env "$@"; }
psql() { dc exec -T postgres psql -U friday -d friday -v ON_ERROR_STOP=1 -At "$@"; }
ORG=$(dc exec -T kernel ./kernel bootstrap "Mama Njeri Supermarket" owner@demo.fridayhost.dev | tail -1)
dc exec -T kernel ./kernel preset "$ORG" supermarket KE 1 5 >/dev/null
# The cashier: staff with the cashier job (sign-in by the demo button only).
psql -c "INSERT INTO core.users (email, password_hash, full_name) VALUES ('cashier@demo.fridayhost.dev', '', 'Wanjiku Kamau') ON CONFLICT (email) DO NOTHING"
psql -c "INSERT INTO core.memberships (org_id, user_id, role, perms) SELECT '$ORG', id, 'member', '{cashier}' FROM core.users WHERE email = 'cashier@demo.fridayhost.dev' ON CONFLICT DO NOTHING"
psql -c "INSERT INTO core.membership_locations (org_id, user_id, location_id) SELECT '$ORG', u.id, l.id FROM core.users u, core.locations l WHERE u.email = 'cashier@demo.fridayhost.dev' AND l.org_id = '$ORG' ON CONFLICT DO NOTHING"
psql -c "UPDATE core.users SET full_name = 'Njeri Mwangi' WHERE email = 'owner@demo.fridayhost.dev'"
dc exec -T invoicing python - < seed.py
dc exec -T postgres pg_dump -U friday -Fc friday > golden.dump.tmp && mv golden.dump.tmp golden.dump
echo "seeded $ORG; golden.dump kept"
