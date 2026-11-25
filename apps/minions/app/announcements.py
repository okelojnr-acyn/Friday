"""Announcements (HR plan 8.2): a message to everyone, a location or a
team, told on the bell, phone and Guss, with who has seen it. Owners and
admins send to anyone; branch managers to their locations (or their
team); team leaders to their team. Who it's for is fixed when it's sent,
so "seen by 4 of 6" stays true."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session, publish_event
from friday_common.access import TEAM_BY_LOCATION, Scope, people_in
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Announcement, AnnouncementRecipient, Employee

router = APIRouter(prefix="/announcements", tags=["announcements"])


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=2000)
    audience: Literal["everyone", "location", "team"]
    location_id: uuid.UUID | None = None


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def _recipients(session: AsyncSession, principal: Principal, body: AnnouncementCreate) -> list[Employee]:
    """Who it goes to, checked against who may send to them."""
    role = principal.role
    staff = select(Employee).where(Employee.org_id == _org(principal), Employee.status == "active", Employee.user_id != "")
    if body.audience == "everyone":
        if role not in ("owner", "admin"):
            raise HTTPException(403, "only owners and admins announce to everyone")
        people = (await session.execute(staff)).scalars().all()
    elif body.audience == "location":
        if body.location_id is None:
            raise HTTPException(422, "choose the location")
        loc = str(body.location_id)
        if role not in ("owner", "admin") and not (role == "branch_manager" and ("*" in principal.locs or loc in principal.locs)):
            raise HTTPException(403, "you announce only to your own locations")
        at = await people_in(Scope(kind="loc", user_id=principal.user_id, locs=(loc,), team=()), principal.org_id)
        people = [e for e in (await session.execute(staff)).scalars().all() if at is None or e.user_id in at]
    else:
        if role not in ("owner", "admin", "branch_manager", "team_leader"):
            raise HTTPException(403, "only team leaders and managers announce to a team")
        team = set(principal.team) - {TEAM_BY_LOCATION}
        people = [e for e in (await session.execute(staff)).scalars().all() if e.user_id in team]
    return [e for e in people if e.user_id != principal.user_id]


async def _author_name(session: AsyncSession, principal: Principal) -> str:
    name = await session.scalar(
        select(Employee.name).where(Employee.org_id == _org(principal), Employee.user_id == principal.user_id)
    )
    return name or principal.email


@router.post("", status_code=201)
async def send_announcement(
    body: AnnouncementCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    people = await _recipients(session, principal, body)
    if not people:
        raise HTTPException(422, "nobody is in that group yet")
    a = Announcement(
        org_id=_org(principal),
        title=body.title.strip(),
        body=body.body.strip(),
        audience=body.audience,
        location_id=body.location_id,
        author_user_id=principal.user_id,
        author_name=await _author_name(session, principal),
        created_at=datetime.now(UTC),
    )
    session.add(a)
    await session.flush()
    for e in people:
        session.add(AnnouncementRecipient(announcement_id=a.id, org_id=a.org_id, user_id=e.user_id, name=e.name))
    await publish_event(
        "minions.announcement.posted",
        principal.org_id,
        {"announcement_id": str(a.id), "to_user_ids": [e.user_id for e in people], "from_name": a.author_name, "description": a.title},
        session=session,
    )
    await session.commit()
    return {"id": str(a.id), "recipients": len(people)}


@router.get("")
async def list_announcements(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The latest 50 sent to me (with whether I've read them) and that I
    sent (with how many have seen them)."""
    mine = select(AnnouncementRecipient.announcement_id).where(AnnouncementRecipient.user_id == principal.user_id)
    rows = (
        await session.execute(
            select(Announcement)
            .where(Announcement.org_id == _org(principal),
                   (Announcement.id.in_(mine)) | (Announcement.author_user_id == principal.user_id))
            .order_by(Announcement.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    ids = [a.id for a in rows]
    counts = {}
    if ids:
        counts = {
            aid: (total, seen)
            for aid, total, seen in (
                await session.execute(
                    select(
                        AnnouncementRecipient.announcement_id,
                        func.count(),
                        func.count(AnnouncementRecipient.read_at),
                    )
                    .where(AnnouncementRecipient.announcement_id.in_(ids))
                    .group_by(AnnouncementRecipient.announcement_id)
                )
            ).all()
        }
    read = {
        aid: at
        for aid, at in (
            await session.execute(
                select(AnnouncementRecipient.announcement_id, AnnouncementRecipient.read_at).where(
                    AnnouncementRecipient.announcement_id.in_(ids), AnnouncementRecipient.user_id == principal.user_id
                )
            )
        ).all()
    } if ids else {}
    out = []
    for a in rows:
        mine_to_send = a.author_user_id == principal.user_id
        total, seen = counts.get(a.id, (0, 0))
        out.append(
            {
                "id": str(a.id),
                "title": a.title,
                "body": a.body,
                "audience": a.audience,
                "author_name": a.author_name,
                "created_at": a.created_at.isoformat(),
                "sent_by_me": mine_to_send,
                "read": mine_to_send or read.get(a.id) is not None,
                **({"recipients": total, "seen": seen} if mine_to_send else {}),
            }
        )
    return out


@router.post("/{announcement_id}/read", status_code=204)
async def mark_read(
    announcement_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    r = await session.get(AnnouncementRecipient, (announcement_id, principal.user_id))
    if r is None or str(r.org_id) != principal.org_id:
        raise HTTPException(404, "announcement not found")
    if r.read_at is None:
        r.read_at = datetime.now(UTC)
        await session.commit()


@router.get("/{announcement_id}/seen")
async def seen_by(
    announcement_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Who it went to and who has seen it: for whoever sent it, and owners."""
    a = await session.get(Announcement, announcement_id)
    if a is None or str(a.org_id) != principal.org_id:
        raise HTTPException(404, "announcement not found")
    if a.author_user_id != principal.user_id and principal.role not in ("owner", "admin"):
        raise HTTPException(403, "only whoever sent it sees who has read it")
    rows = (
        await session.execute(
            select(AnnouncementRecipient).where(AnnouncementRecipient.announcement_id == a.id).order_by(AnnouncementRecipient.name)
        )
    ).scalars().all()
    return [{"name": r.name, "read_at": r.read_at.isoformat() if r.read_at else None} for r in rows]
