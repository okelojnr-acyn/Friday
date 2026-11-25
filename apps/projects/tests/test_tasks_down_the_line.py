"""HR plan 8.4.2: tasks go down the reporting line. A team leader gives
their team tasks; staff only give themselves one; the person is told,
the giver hears when it's done, and overdue tasks go to both, then up."""

from datetime import UTC, datetime, timedelta

import pytest
from friday_common.access import Approvers
from friday_common.testing import make_principal


PEOPLE = {
    "u-tom": {"user_id": "u-tom", "role": "team_leader", "name": "Tom", "email": "tom@x.test"},
    "u-sam": {"user_id": "u-sam", "role": "member", "name": "Sam", "email": "sam@x.test"},
    "u-ann": {"user_id": "u-ann", "role": "member", "name": "Ann", "email": "ann@x.test"},
    "u-bea": {"user_id": "u-bea", "role": "branch_manager", "name": "Bea", "email": "bea@x.test"},
}


def who(principal, uid, role="member", team=()):
    p = make_principal(org_id=principal.org_id, role=role, email=PEOPLE[uid]["email"], team=team)
    return p.__class__(**{**p.__dict__, "user_id": uid})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    async def person(_org, *, user_id="", email=""):
        for p in PEOPLE.values():
            if (user_id and p["user_id"] == user_id) or (not user_id and p["email"] == email.lower()):
                return p
        return None

    async def line(_org, user_id):
        # Sam -> Tom -> Bea.
        chain = {"u-sam": ("u-tom", "u-bea"), "u-tom": ("u-bea",)}.get(user_id, ())
        return Approvers(limits={}, chain=tuple(PEOPLE[u] for u in chain), top=())

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    monkeypatch.setattr("app.main.person_in_business", person)
    monkeypatch.setattr("app.main.approvers_for", line)
    return sent


async def test_a_team_leader_gives_their_team_a_task_and_staff_cannot(client, as_principal, principal, events):
    tom = who(principal, "u-tom", "team_leader", team=("u-sam",))
    as_principal(tom)
    r = await client.post("/tasks", json={"title": "Count shelf 4", "assignee_user_id": "u-sam"})
    assert r.status_code == 201
    task = r.json()
    assert (task["assignee_name"], task["assigned_by_name"], task["assignee_email"]) == ("Sam", "Tom", "sam@x.test")
    assert events == [("projects.task.assigned", events[0][1])]
    assert events[0][1]["to_user_ids"] == ["u-sam"] and events[0][1]["from_name"] == "Tom"

    # Not his team: Ann. Not in the business at all: a stranger's email.
    r = await client.post("/tasks", json={"title": "x", "assignee_user_id": "u-ann"})
    assert r.status_code == 403 and "isn't in your team" in r.json()["detail"]
    assert (await client.post("/tasks", json={"title": "x", "assignee_email": "nobody@x.test"})).status_code == 422

    # Staff give tasks only to themselves.
    as_principal(who(principal, "u-sam"))
    assert (await client.post("/tasks", json={"title": "x", "assignee_user_id": "u-ann"})).status_code == 403
    mine = await client.post("/tasks", json={"title": "Note to self", "assignee_user_id": "u-sam"})
    assert mine.status_code == 201 and len(events) == 1  # no notice to yourself


async def test_who_sees_which_tasks(client, as_principal, principal, events):
    as_principal(who(principal, "u-tom", "team_leader", team=("u-sam",)))
    for_sam = (await client.post("/tasks", json={"title": "For Sam", "assignee_user_id": "u-sam"})).json()
    as_principal(who(principal, "u-ann"))
    anns = (await client.post("/tasks", json={"title": "Ann's own", "assignee_user_id": "u-ann"})).json()

    as_principal(who(principal, "u-sam"))
    assert [t["id"] for t in (await client.get("/tasks?mine=true")).json()] == [for_sam["id"]]
    assert {t["id"] for t in (await client.get("/tasks")).json()} == {for_sam["id"]}  # not Ann's
    as_principal(who(principal, "u-tom", "team_leader", team=("u-sam",)))
    assert {t["id"] for t in (await client.get("/tasks")).json()} == {for_sam["id"]}
    as_principal(make_principal(org_id=principal.org_id, role="owner"))
    assert {t["id"] for t in (await client.get("/tasks")).json()} >= {for_sam["id"], anns["id"]}


async def test_the_person_changes_the_status_and_the_giver_hears_it_is_done(client, as_principal, principal, events):
    as_principal(who(principal, "u-tom", "team_leader", team=("u-sam",)))
    task = (await client.post("/tasks", json={"title": "Count shelf 4", "assignee_user_id": "u-sam"})).json()
    as_principal(who(principal, "u-sam"))
    r = await client.patch(f"/tasks/{task['id']}", json={"title": "Count nothing"})
    assert r.status_code == 403
    r = await client.patch(f"/tasks/{task['id']}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["done_at"]
    done = [p for e, p in events if e == "projects.task.done"]
    assert done and done[0]["to_user_ids"] == ["u-tom"] and done[0]["from_name"] == "Sam"
    # Someone outside it doesn't even see it.
    as_principal(who(principal, "u-ann"))
    assert (await client.patch(f"/tasks/{task['id']}", json={"status": "todo"})).status_code == 404


async def test_overdue_goes_to_both_then_up_the_line(client, as_principal, principal, events, kernel_auth_header):
    as_principal(who(principal, "u-tom", "team_leader", team=("u-sam",)))
    due = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    late = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    soon = (await client.post("/tasks", json={"title": "Due today", "assignee_user_id": "u-sam", "due_at": due})).json()
    old = (await client.post("/tasks", json={"title": "Long late", "assignee_user_id": "u-sam", "due_at": late})).json()
    tick = lambda: client.post("/internal/webhooks/hourly", json={"org_id": principal.org_id}, headers=kernel_auth_header)  # noqa: E731
    assert (await tick()).status_code == 204
    overdue = [p for e, p in events if e == "projects.task.overdue"]
    assert {(p["task"], tuple(p["to_user_ids"]), p["level"]) for p in overdue} == {
        ("Due today", ("u-sam", "u-tom"), 1),
        ("Long late", ("u-sam", "u-tom"), 1),
    }
    await tick()  # the next hour: only the 3-days-late one goes up, to Tom's boss
    overdue = [p for e, p in events if e == "projects.task.overdue"]
    assert [(p["task"], p["to_user_ids"], p["level"]) for p in overdue[2:]] == [("Long late", ["u-bea"], 2)]
    await tick()
    assert len([e for e, _ in events if e == "projects.task.overdue"]) == 3  # nothing more
    assert soon["id"] and old["id"]
