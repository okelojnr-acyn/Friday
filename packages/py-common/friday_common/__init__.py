"""Shared building blocks every Friday app is built from.

Nothing in here is app-specific. An app (apps/crm, apps/invoicing, ...)
should never reimplement auth, db sessions, event publishing, or the
resource-schema contract the web shell renders from -- it imports this
package instead. That's what keeps four independently-built apps behaving
like one product, and what keeps an update to one app from silently
breaking another.
"""

from .settings import FridaySettings, get_settings
from .auth import Principal, get_current_principal, require_role
from .db import get_session, get_org_session, make_engine, set_org_context
from .events import publish_event, require_kernel_token
from .resource import FieldSpec, ResourceSpec, resource
from .app_factory import create_app
from .integrations import get_integration_config

__all__ = [
    "FridaySettings",
    "get_settings",
    "Principal",
    "get_current_principal",
    "require_role",
    "get_session",
    "get_org_session",
    "make_engine",
    "set_org_context",
    "publish_event",
    "require_kernel_token",
    "FieldSpec",
    "ResourceSpec",
    "resource",
    "create_app",
    "get_integration_config",
]
