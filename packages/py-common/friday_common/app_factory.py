from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .db import make_engine
from .resource import all_resources
from .settings import get_settings


def create_app(service_name: str, version: str = "0.1.0") -> FastAPI:
    """Every app service calls this once instead of configuring FastAPI
    from scratch, so health checks, CORS, OpenAPI tagging, and the schema
    endpoint behave identically across apps/crm, apps/invoicing, and
    apps/projects.
    """
    settings = get_settings()
    app = FastAPI(title=service_name, version=version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    system = APIRouter(tags=["system"])

    @system.get("/healthz")
    def healthz() -> dict:
        """Liveness only: the process is up. Says nothing about the DB --
        on 2026-11-10 this returned ok all day while every query 500'd."""
        return {"status": "ok", "service": service_name}

    @system.get("/health")
    async def health() -> JSONResponse:
        """Readiness: run a real query through the *same* engine request
        handlers use (same URL adaptation, same PgBouncer path), against
        this app's own schema. 503 with the error class on failure, so a
        deploy check or the kernel's /health/apps aggregate catches a
        broken DATABASE_URL before a user does. Error *text* is omitted --
        it can contain connection details."""
        try:
            async with make_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
                if settings.db_schema != "public":
                    found = await conn.execute(
                        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                        {"s": settings.db_schema},
                    )
                    if found.first() is None:
                        raise LookupError(f"schema {settings.db_schema!r} missing")
        except Exception as exc:  # noqa: BLE001 -- report any failure as not-ready
            return JSONResponse(
                status_code=503,
                content={"status": "error", "service": service_name, "error": type(exc).__name__},
            )
        return JSONResponse({"status": "ok", "service": service_name, "db": "ok"})

    @system.get("/schema")
    def schema() -> list[dict]:
        """Every resource this app has registered, as the web shell's
        generic renderer expects it. This is how a new app becomes
        navigable with zero custom frontend code."""
        return [r.to_json() for r in all_resources()]

    app.include_router(system)
    return app
