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

import jwt
from pathlib import Path

from fastapi import Depends, HTTPException, status

from .auth import ROLE_RANK, Principal, get_current_principal
from .settings import get_settings

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
# none). Defaults only: each business sets its own (kernel
# /orgs/approval-limits, read through approvers_for).
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
    if scope.kind == "all":
        return None
    if scope.kind == "loc" or TEAM_BY_LOCATION in scope.team:
        # "All locations" widens location scopes only, never team or own.
        if "*" in scope.locs:
            return None
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


@dataclass(frozen=True)
class Approvers:
    """Who a request from one person goes to (kernel
    /internal/people/{org}/approvers/{user}): `chain` up reports_to,
    nearest first; `top` the owners and admins; `limits` per role, cents."""

    limits: dict[str, int]
    chain: tuple[dict, ...]
    top: tuple[dict, ...]

    def pick(self, amount_cents: int) -> dict | None:
        """The nearest person up the line who may decide this amount; None
        when nobody in the line may (it goes to the owners and admins)."""
        for person in self.chain:
            if person.get("role") in ("owner", "admin"):
                return person
            limit = self.limits.get(person.get("role", ""))
            if limit is not None and amount_cents <= limit:
                return person
        return None


async def approvers_for(org_id: str, user_id: str) -> Approvers:
    """Asks the kernel; if it can't answer, the default limits and nobody
    named, so a request still goes to the owners and admins (never lost)."""
    import httpx

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/people/{org_id}/approvers/{user_id}",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            body = resp.json()
        limits = {k: int(v) for k, v in body["limits"].items()}
        return Approvers(limits=limits, chain=tuple(body["chain"]), top=tuple(body["top"]))
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return Approvers(limits=dict(APPROVAL_LIMIT_CENTS), chain=(), top=())


# The Standard spending policy (kernel org/spending.go keeps the same
# numbers): what applies until a business picks another, or on a kernel
# from before the setting.
STANDARD_SPENDING = {
    "preset": "standard", "ask_first_member": 200_000, "ask_first_team_leader": 1_000_000,
    "ask_first_branch_manager": 5_000_000, "trips_ask_first": True, "no_receipt_under": 100_000,
    "no_receipt_per_year": 3, "tolerance_pct": 10, "till_payouts": False,
    "petty_float": 1_000_000, "petty_slip_max": 200_000, "till_discount_pct": 10,
}


async def spending_policy(org_id: str) -> dict:
    """The business's spending policy (Business settings > Spending).
    Standard on a kernel without the setting; 503 when the kernel can't
    answer (never guesses a looser rule)."""
    import httpx

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/people/{org_id}/spending-policy",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
        if resp.status_code == 404:
            return dict(STANDARD_SPENDING)
        resp.raise_for_status()
        return {**STANDARD_SPENDING, **resp.json()}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"couldn't read the spending policy: {exc}") from exc


async def person_in_business(org_id: str, *, user_id: str = "", email: str = "") -> dict | None:
    """One member of the business ({user_id, role, name, email}) by id or
    email; None when they aren't one. Raises 503 when the kernel can't say
    (never guesses who someone is)."""
    import httpx

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/people/{org_id}/person",
                params={"user_id": user_id, "email": email},
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"couldn't check who that is: {exc}") from exc


def require_place(scope: Scope, location_id, what: str = "that place") -> None:
    """Refuses something at a location outside the caller's. Something
    nobody has placed yet (no location) stays open to whoever the rule
    allows."""
    if location_id is not None and not scope.allows_location(str(location_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{what} is at a location that isn't yours")


def whole_business(scope: Scope) -> None:
    """For what has no location (the books, the treasury): a scope limited
    to some locations doesn't cover it."""
    if not scope.everywhere:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this covers the whole business; ask an admin")


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


APPROVAL_HEADER = "X-Friday-Approval"
APPROVERS = ("owner", "admin", "branch_manager", "team_leader")


def check_approval(token: str | None, principal: Principal, *, amount_cents: int, location_id: str | None) -> str:
    """A staff action someone over them approved at the till (the kernel's
    POST /auth/pos/approve: a team leader's or manager's PIN, two minutes).
    The approver is someone else, over this person (their team, or the
    place) and within their limit. Returns the approver's user id; 428
    asks for an approval, 403 says why this one won't do."""
    if not token:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "a team leader's or manager's approval is needed")
    settings = get_settings()
    try:
        c = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "the approval ran out; approve again") from None
    role = c.get("role", "")
    if c.get("via") != "pos-approval" or c.get("org_id") != principal.org_id or role not in APPROVERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "that isn't an approval from this business")
    if c.get("sub") == principal.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "someone else approves your return")
    if role == "team_leader" and principal.user_id not in (c.get("team") or ()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you aren't in that team leader's team; ask your own, or a manager")
    if role == "branch_manager" and "*" not in (c.get("locs") or ()) and str(location_id) not in (c.get("locs") or ()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "that manager isn't over this location")
    limit = APPROVAL_LIMIT_CENTS.get(role)
    if limit is not None and amount_cents > limit:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"above {ROLE_NAMES.get(role, role)}'s limit ({limit // 100:,}); ask {who_can('pos.sell', role)}"
        )
    return str(c.get("sub"))


# A till sale can sync long after its approval was given (an offline
# till), so a sale's approval is judged by when it was issued, not by its
# two-minute expiry.
SALE_APPROVAL_MAX_AGE_S = 24 * 3600


def sale_approver(token: str | None, principal: Principal, *, now: float | None = None) -> str:
    """Who approved a till sale's price cut or big discount, from the
    kernel's signed approval (POST /auth/pos/approve) sent with the sale:
    their email when the approval is genuine, from this business, from a
    leader or manager other than the cashier, and at most a day old.
    "" when there's none, "unverified" when one was sent but won't do. A
    sale is never refused for it: the money has already changed hands."""
    import time

    if not token:
        return ""
    settings = get_settings()
    try:
        c = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"verify_exp": False})
    except jwt.PyJWTError:
        return "unverified"
    age = (now if now is not None else time.time()) - float(c.get("iat") or 0)
    if (
        c.get("via") != "pos-approval"
        or c.get("org_id") != principal.org_id
        or c.get("role") not in APPROVERS
        or c.get("sub") == principal.user_id
        or not 0 <= age <= SALE_APPROVAL_MAX_AGE_S
    ):
        return "unverified"
    return str(c.get("email") or c.get("sub"))
