"""Regression test for the 2026-11-10 production outage: Friday Host's
`?sslmode=require` DATABASE_URL made every asyncpg connection raise
`TypeError: connect() got an unexpected keyword argument 'sslmode'`.
Lives under crm only because CI runs pytest per app; it tests py-common.
"""

from friday_common.db import engine_args


def test_sslmode_becomes_asyncpg_ssl_and_leaves_the_url():
    url, connect_args = engine_args("postgresql+asyncpg://u:p@db.example:6432/x?sslmode=require")
    assert "sslmode" not in url.query
    assert connect_args["ssl"] == "require"


def test_pgbouncer_transaction_pooling_settings():
    url, connect_args = engine_args("postgresql+asyncpg://u:p@localhost/x")
    assert url.query["prepared_statement_cache_size"] == "0"
    assert connect_args["statement_cache_size"] == 0
    name_func = connect_args["prepared_statement_name_func"]
    assert name_func() != name_func()
    assert "ssl" not in connect_args
