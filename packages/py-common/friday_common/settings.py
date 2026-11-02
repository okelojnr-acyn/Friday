from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class FridaySettings(BaseSettings):
    """Env-driven config shared by every app service.

    Every app reads the same variable names, set once in .env, so adding an
    app never means inventing a new config convention.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "friday-app"
    database_url: str = "postgresql+asyncpg://friday:friday@localhost:5432/friday"
    db_schema: str = "public"

    # Shared HS256 secret the kernel signs session JWTs with. Every app
    # verifies with the same secret instead of calling back into the kernel
    # on every request. Self-hosted/single-deployment trust boundary; swap
    # for RS256 + JWKS if you need cross-deployment verification.
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"

    # Where this app posts domain events for the kernel to fan out to
    # subscribers (other apps' webhook endpoints). Deliberately HTTP, not a
    # message broker -- see ARCHITECTURE.md for why.
    kernel_internal_url: str = "http://localhost:8080/internal"
    kernel_events_token: str = "dev-only-change-me"

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> FridaySettings:
    return FridaySettings()
