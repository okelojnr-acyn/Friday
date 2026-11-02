from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
        return {"status": "ok", "service": service_name}

    @system.get("/schema")
    def schema() -> list[dict]:
        """Every resource this app has registered, as the web shell's
        generic renderer expects it. This is how a new app becomes
        navigable with zero custom frontend code."""
        return [r.to_json() for r in all_resources()]

    app.include_router(system)
    return app
