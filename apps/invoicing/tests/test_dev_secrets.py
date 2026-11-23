"""The built-in development secrets never run outside development
(security review #5): a kernel or app started without JWT_SECRET or
KERNEL_EVENTS_TOKEN would accept forged sign-ins."""

from friday_common.settings import DEV_SECRET, FridaySettings, weak_secrets


def test_dev_secrets_refused_unless_this_is_development(monkeypatch):
    monkeypatch.delenv("FRIDAY_DEV", raising=False)
    shared = FridaySettings(database_url="postgresql+asyncpg://u:p@pgbouncer:6432/db", jwt_secret=DEV_SECRET, kernel_events_token="x" * 64)
    assert weak_secrets(shared) == ["JWT_SECRET"]
    local = FridaySettings(database_url="postgresql+asyncpg://u:p@localhost:5432/db", jwt_secret=DEV_SECRET)
    assert weak_secrets(local) == []
    monkeypatch.setenv("FRIDAY_DEV", "1")
    assert weak_secrets(shared) == []
