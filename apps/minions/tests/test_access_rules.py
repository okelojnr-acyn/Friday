"""The rules table (friday_common/access.py, plan section 12): scopes by
role and permission, what "team" and "loc" let through, and who to ask.
Pure logic; the same table drives the kernel (its own tests check the
two copies match)."""

import pytest
from fastapi import HTTPException

from friday_common.access import Scope, require, scope_for, scope_of, who_can
from friday_common.testing import make_principal


@pytest.mark.parametrize(
    "role, perms, rule, want",
    [
        ("member", (), "pos.sell", ""),
        ("member", ("cashier",), "pos.sell", "loc"),
        ("team_leader", ("warehouse",), "pos.sell", ""),
        ("branch_manager", (), "pos.sell", "loc"),
        ("owner", (), "pos.sell", "all"),
        ("member", (), "sales.read", "own"),
        ("team_leader", (), "sales.read", "team"),
        ("viewer", (), "sales.read", "all"),
        ("admin", (), "pay.read", "all"),
        ("branch_manager", (), "pay.write", ""),
        ("viewer", ("accounting",), "books.read", "all"),
        ("viewer", (), "books.read", ""),
    ],
)
def test_scope_of(role, perms, rule, want):
    assert scope_of(role, perms, rule) == want


def test_team_and_own_see_only_their_people():
    lead = Scope(kind="team", user_id="lead", locs=("L1",), team=("a", "b"))
    assert lead.allows_person("a") and lead.allows_person("lead")
    assert not lead.allows_person("c") and not lead.allows_person(None)
    assert lead.people() == {"lead", "a", "b"}
    me = Scope(kind="own", user_id="me", locs=("*",), team=())
    assert me.allows_person("me") and not me.allows_person("lead")
    big = Scope(kind="team", user_id="lead", locs=("L1",), team=("*loc",))
    assert big.people() is None and big.allows_location("L1") and not big.allows_location("L2")


def test_loc_sees_only_its_locations_and_no_locations_means_none():
    branch = Scope(kind="loc", user_id="m", locs=("L1", "L2"), team=())
    assert branch.allows_location("L1") and not branch.allows_location("L3")
    assert not branch.allows_location(None)
    assert Scope(kind="loc", user_id="m", locs=("*",), team=()).allows_location("L9")
    nowhere = scope_for(make_principal(role="branch_manager", locs=()), "sales.read")
    assert nowhere is not None and not nowhere.allows_location("L1")


def test_refusals_name_who_can():
    assert who_can("pay.write", "branch_manager") == "an admin"  # admins hold every permission
    assert who_can("sales.refund", "member") == "a team leader"
    check = require("pay.write")
    with pytest.raises(HTTPException) as e:
        check(make_principal(role="branch_manager"))
    assert e.value.status_code == 403 and "ask an admin" in e.value.detail
    assert check(make_principal(role="owner")).kind == "all"
