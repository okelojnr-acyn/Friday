"""Who sees what (plan section 12): the rules every app enforces.

`access_rules.json` is the same file as the kernel's
kernel/internal/access/rules.json (a kernel test fails if they differ):
rule -> role -> scope. A route asks for its rule and gets the caller's
scope, then filters by it:

    scope: Scope = Depends(require("sales.read"))
    q = scope.filter_people(q, Invoice.cashier_user_id)

Scopes: all; loc (their locations); team (people who report to them, and
themselves); own (their own records). '+perm' needs that permission;
owners and admins hold every permission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, status

from .auth import ROLE_RANK, Principal, get_current_principal

RULES: dict[str, dict[str, str]] = {
    k: v
    for k, v in json.loads((Path(__file__).parent / "access_rules.json").read_text(encoding="utf-8")).items()
    if not k.startswith("_")
}
PERMS = ("cashier", "warehouse", "logistics", "purchasing", "sales", "accounting", "hr")
# Stands in for a team too big to list in a token (kernel access.TeamByLocation).
TEAM_BY_LOCATION = "*loc"

# Approval limits per item, in the currency's cents (plan 12.9: KES 2,000
# for team leaders, KES 20,000 for branch managers; owners and admins have
# none). shortcut: one limit for every business and currency; make them a
# business setting when a business asks.
APPROVAL_LIMIT_CENTS = {"team_leader": 200_000, "branch_manager": 2_000_000}

ROLE_NAMES = {
    "owner": "an owner",
    "admin": "an admin",
    "branch_manager": "a branch manager",
    "team_leader": "a team leader",
    "member": "staff",
    "viewer": "a viewer",
}


def scope_of(role: str, perms: tuple[str, ...] | list[str], rule: str) -> str:
    """The scope `role` with `perms` has under `rule`, "" for none. Mirrors
    the kernel's access.Scope."""
    spec = RULES.get(rule, {}).get(role, "")
    if not spec:
        return ""
    scope, _, need = spec.partition("+")
    if not need or role in ("owner", "admin"):
        return scope
    return scope if any(p in perms for p in need.split("|")) else ""


def who_can(rule: str, above: str) -> str:
    """The lowest role above `above` that may do `rule`, as words."""
    allowed = [r for r in RULES.get(rule, {}) if ROLE_RANK.get(r, -1) > ROLE_RANK.get(above, -1)]
    if not allowed:
        return "an owner"
    return ROLE_NAMES.get(min(allowed, key=lambda r: ROLE_RANK.get(r, 99)), "an owner")


@dataclass(frozen=True)
class Scope:
    """What the caller may see or change under one rule."""

    kind: str  # all | loc | team | own
    user_id: str
    locs: tuple[str, ...]
    team: tuple[str, ...]

    @property
    def everywhere(self) -> bool:
        return self.kind == "all" or (self.kind == "loc" and "*" in self.locs)

    def allows_location(self, location_id: str | None) -> bool:
        """A record at this location (None = not tied to one). team and own
        are filtered by person, not place."""
        if self.everywhere:
            return True
        if self.kind == "loc" or (self.kind == "team" and TEAM_BY_LOCATION in self.team):
            return location_id is not None and ("*" in self.locs or str(location_id) in self.locs)
        return True

    def allows_person(self, user_id: str | None) -> bool:
        """A record belonging to this person (its cashier, owner, author)."""
        if self.kind in ("all", "loc"):
            return True
        if self.kind == "team" and TEAM_BY_LOCATION in self.team:
            return True
        people = {self.user_id, *self.team} if self.kind == "team" else {self.user_id}
        return user_id is not None and str(user_id) in people

    def people(self) -> set[str] | None:
        """Whose records may be seen: None = anyone's."""
        if self.kind in ("all", "loc") or TEAM_BY_LOCATION in self.team:
            return None
        return {self.user_id, *self.team} if self.kind == "team" else {self.user_id}

    def filter_people(self, query, column):
        """Adds "this person, or their team" to a SQLAlchemy query."""
        who = self.people()
        return query if who is None else query.where(column.in_(list(who)))


async def people_in(scope: Scope, org_id: str) -> set[str] | None:
    """Whose records `scope` may see: None for anyone's; for "loc", everyone
    at those locations (asked of the kernel, which knows who works where;
    someone with no locations listed works at all of them). Refuses when
    the kernel can't answer: closed, never open."""
    if scope.kind == "all" or "*" in scope.locs:
        return None
    if scope.kind == "loc" or TEAM_BY_LOCATION in scope.team:
        import httpx

        from .settings import get_settings

        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.kernel_internal_url}/people/{org_id}",
                    params=[("location", loc) for loc in scope.locs],
                    headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
                )
                resp.raise_for_status()
                return set(resp.json()["user_ids"]) | {scope.user_id}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"couldn't check who works where: {exc}") from exc
    return scope.people()


def scope_for(principal: Principal, rule: str) -> Scope | None:
    kind = scope_of(principal.role, principal.perms, rule)
    if not kind:
        return None
    # No locations in the token means none (the kernel couldn't load them),
    # never all.
    return Scope(kind=kind, user_id=principal.user_id, locs=principal.locs, team=principal.team)


def require(rule: str):
    """Dependency: the caller's Scope under `rule`, or 403 naming who can."""

    def _check(principal: Principal = Depends(get_current_principal)) -> Scope:
        scope = scope_for(principal, rule)
        if scope is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"your role can't do this ({rule}); ask {who_can(rule, principal.role)}",
            )
        return scope

    return _check
