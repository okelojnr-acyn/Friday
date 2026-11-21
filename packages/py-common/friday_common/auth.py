from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import get_settings

_bearer = HTTPBearer(auto_error=False)

# The role ladder (plan section 12.1). "member" is staff. What each role
# may see and do beyond "at least this rank" is in access.py.
ROLE_RANK = {"viewer": 0, "member": 1, "team_leader": 2, "branch_manager": 3, "admin": 4, "owner": 5}


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: str
    role: str
    email: str
    # Set when an assistant (Guss) acts for the person; see the kernel's
    # Claims.Via. Routes a person must run themselves check it.
    via: str = ""
    # Plan section 12: permissions, locations ("*" = all) and the people
    # who report to them, from the token (see access.py).
    perms: tuple[str, ...] = ()
    locs: tuple[str, ...] = ()
    team: tuple[str, ...] = ()

    def at_least(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK.get(role, 99)


def get_current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """FastAPI dependency: verifies the kernel-issued JWT and returns who's
    calling. Every org-scoped query in an app should filter by
    `principal.org_id` -- Postgres RLS is the backstop, not the only check.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    settings = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc

    try:
        return Principal(
            user_id=payload["sub"],
            org_id=payload["org_id"],
            role=payload["role"],
            email=payload["email"],
            via=payload.get("via", ""),
            perms=tuple(payload.get("perms") or ()),
            locs=tuple(payload.get("locs") or ()),
            team=tuple(payload.get("team") or ()),
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"token missing claim: {exc}") from exc


def require_role(role: str):
    """Dependency factory: `Depends(require_role("admin"))` on any route."""

    def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.at_least(role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"requires role '{role}' or higher, you have '{principal.role}'",
            )
        return principal

    return _check
