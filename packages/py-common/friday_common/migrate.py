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
        for f in sorted(migrations_dir.glob("*.sql")):
            already = await conn.fetchval(
                f'SELECT 1 FROM "{schema}".schema_migrations WHERE filename = $1', f.name
            )
            if already:
                continue
            sql = f.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(f'SET search_path TO "{schema}", public')
                await conn.execute(sql)
                await conn.execute(
                    f'INSERT INTO "{schema}".schema_migrations (filename) VALUES ($1)', f.name
                )
            applied.append(f.name)
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
