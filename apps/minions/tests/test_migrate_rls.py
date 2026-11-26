"""2026-11-26: minions 0016 (an UPDATE of existing claims) crashed the
update on a box with claims: forced row-level security, no business set,
'' as a uuid. CI missed it (no rows, and a superuser skips RLS). The
runner now lifts FORCE for each migration's transaction; this replays the
case as an ordinary owner role with a row already there."""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from friday_common.migrate import run_migrations
from friday_common.testing import test_dsn as dsn_for_tests  # not collected as a test

STEPS = {
    "0001_t.sql": """CREATE TABLE t (id INT PRIMARY KEY, org_id UUID NOT NULL, v TEXT NOT NULL DEFAULT 'old');
        ALTER TABLE t ENABLE ROW LEVEL SECURITY; ALTER TABLE t FORCE ROW LEVEL SECURITY;
        CREATE POLICY t_org ON t USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);""",
    "0002_row.sql": f"INSERT INTO t (id, org_id) VALUES (1, '{uuid.uuid4()}');",
    "0003_update.sql": "UPDATE t SET v = 'new';",
}


async def test_a_migration_changes_rows_under_forced_rls(tmp_path):
    role, schema = "migrate_rls_owner", "migrate_rls_test"
    admin = await asyncpg.connect(os.environ.get("ADMIN_DATABASE_URL") or dsn_for_tests())  # one that makes roles
    db = await admin.fetchval("SELECT current_database()")
    try:
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f"DROP ROLE IF EXISTS {role}")
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOSUPERUSER NOBYPASSRLS")
        await admin.execute(f'GRANT CREATE ON DATABASE "{db}" TO {role}')
        # A pooled connection that once served a business: '' afterwards.
        await admin.execute(f"ALTER ROLE {role} SET app.current_org_id = ''")
        for name, sql in STEPS.items():
            (tmp_path / name).write_text(sql, encoding="utf-8")
        parts = urlsplit(dsn_for_tests())
        as_role = urlunsplit(parts._replace(netloc=f"{role}:pw@{parts.hostname}:{parts.port or 5432}"))
        assert await run_migrations(as_role, schema, tmp_path) == [*(f"common/{n}" for n in _common()), *STEPS]
        assert await admin.fetchval(f'SELECT v FROM "{schema}".t') == "new"
        forced = await admin.fetchval(f"SELECT relforcerowsecurity FROM pg_class WHERE oid = '\"{schema}\".t'::regclass")
        assert forced  # put back
    finally:
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'REVOKE ALL ON DATABASE "{db}" FROM {role}')
        await admin.execute(f"DROP ROLE IF EXISTS {role}")
        await admin.close()


def _common() -> list[str]:
    from friday_common.migrate import COMMON_MIGRATIONS

    return [f.name for f in sorted(COMMON_MIGRATIONS.glob("*.sql"))]
