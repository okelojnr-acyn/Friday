"""Roadmap item 4: a till sale keeps who approved its price cut or big
discount, checked from the manager's signed approval (never the till's
word), and an offline sale's day-old approval still counts."""

import time
import uuid

import jwt
from friday_common.settings import get_settings


def approval(principal, *, role="branch_manager", sub=None, iat=None, org=None):
    s = get_settings()
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "org_id": org or principal.org_id,
        "role": role,
        "email": "manager@shop.test",
        "via": "pos-approval",
        "iat": int(iat if iat is not None else time.time()),
        "exp": int(time.time()) - 60,  # long expired: offline sync
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


async def sell(client, **extra):
    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Rice", "quantity": 1, "unit_price_cents": 40_000, "discount_bp": 1500}],
            "amount_cents": 34_000,
            "method": "cash",
            **extra,
        },
    )
    assert resp.status_code == 201
    return resp.json()["override_approved_by"]


async def test_the_signed_approver_is_kept_and_a_typed_name_is_not(client, principal):
    assert await sell(client, override_approval=approval(principal)) == "manager@shop.test"
    assert await sell(client, override_approved_by="boss@shop.test") == ""


async def test_approvals_that_wont_do_are_marked_not_refused(client, principal):
    assert await sell(client, override_approval=approval(principal, role="member")) == "unverified"
    assert await sell(client, override_approval=approval(principal, sub=principal.user_id)) == "unverified"
    assert await sell(client, override_approval=approval(principal, iat=time.time() - 2 * 86400)) == "unverified"
    assert await sell(client, override_approval="not-a-token") == "unverified"
