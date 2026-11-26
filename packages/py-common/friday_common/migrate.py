"""The same tiny numbered-SQL-files migration approach the Go kernel uses
(kernel/internal/db/db.go), so there's exactly one migration mental model
in the whole repo, not a Go one and a Python one.

Usage: `python -m friday_common.migrate apps/crm crm`
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

COMMON_MIGRATIONS = Path(__file__).parent / "migrations"


async def run_migrations(dsn: str, schema: str, migrations_dir: Path) -> list[str]:
    conn = await asyncpg.connect(dsn)
    applied: list[str] = []
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        # Shared tables every app has (friday_common/migrations, e.g. the
        # event outbox), then the app's own. Shared ones are recorded as
        # "common/<file>" so their names never clash with an app's.
        common = [(f"common/{f.name}", f) for f in sorted(COMMON_MIGRATIONS.glob("*.sql"))]
        own = [(f.name, f) for f in sorted(migrations_dir.glob("*.sql"))]
        for name, f in common + own:
            already = await conn.fetchval(
                f'SELECT 1 FROM "{schema}".schema_migrations WHERE filename = $1', name
            )
            if already:
                continue
            sql = f.read_text(encoding="utf-8")
            async with conn.transaction():
                # LOCAL: behind PgBouncer transaction pooling a plain SET
                # would outlive this transaction on the shared server conn.
                await conn.execute(f'SET LOCAL search_path TO "{schema}", public')
                # Friday Host gives tenant roles a statement timeout; a
                # migration on a big table may need longer.
                await conn.execute("SET LOCAL statement_timeout = 0")
                # A migration changes every business's rows, but forced
                # row-level security shows it none (no business is set) or
                # fails on '' as a uuid (2026-11-26: minions 0016 never ran
                # on a box with claims). Lift FORCE for this transaction;
                # the owner then sees all rows. Put back before commit.
                forced = await conn.fetch(
                    """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = $1 AND c.relkind = 'r' AND c.relforcerowsecurity
                         AND pg_has_role(c.relowner, 'USAGE')""",
                    schema,
                )
                for row in forced:
                    await conn.execute(f'ALTER TABLE "{schema}"."{row["relname"]}" NO FORCE ROW LEVEL SECURITY')
                await conn.execute(sql)
                # shortcut: a migration can't drop FORCE on a table that had it; add an opt-out if one ever must.
                still = await conn.fetch(
                    """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = $1 AND c.relname = ANY($2::text[])""",
                    schema,
                    [row["relname"] for row in forced],
                )
                for row in still:  # a table the migration dropped is gone
                    await conn.execute(f'ALTER TABLE "{schema}"."{row["relname"]}" FORCE ROW LEVEL SECURITY')
                await conn.execute(
                    f'INSERT INTO "{schema}".schema_migrations (filename) VALUES ($1)', name
                )
            applied.append(name)
    finally:
        await conn.close()
    return applied


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python -m friday_common.migrate <app_dir> <schema_name>", file=sys.stderr)
        sys.exit(1)

    app_dir = Path(sys.argv[1])
    schema = sys.argv[2]
    dsn = os.environ.get("DATABASE_URL", "postgresql://friday:friday@localhost:5432/friday")
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    applied = asyncio.run(run_migrations(dsn, schema, app_dir / "migrations"))
    if applied:
        print(f"applied to schema '{schema}': {', '.join(applied)}")
    else:
        print(f"schema '{schema}' already up to date")


if __name__ == "__main__":
    main()
