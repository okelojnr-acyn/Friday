import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    first_delivery,
    get_session,
    publish_event,
    require_kernel_token,
    resource,
    set_org_context,
)
from friday_common.clock import business_tz, local_midnight
from friday_common.access import Scope, approvers_for, people_in, person_in_business, require, scope_for, who_can
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    PROJECT_STATUSES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TICKET_PRIORITIES,
    TICKET_STATUSES,
    Project,
    Task,
    Ticket,
    TimeEntry,
)
from .schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TicketCreate,
    TicketOut,
    TicketUpdate,
    TimeEntryCreate,
    TimeEntryOut,
)

resource(
    ResourceSpec(
        name="project",
        app="projects",
        label="Project",
        label_plural="Projects",
        views=("list", "form"),
        search_fields=("name",),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("description", "Description", "textarea", list_visible=False),
            FieldSpec("status", "Status", "select", options=PROJECT_STATUSES, required=True),
            FieldSpec(
                "opportunity_id", "Won opportunity", "reference", reference="crm.opportunity", list_visible=False
            ),
            FieldSpec("budget_cents", "Budget", "currency", list_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="task",
        app="projects",
        label="Task",
        label_plural="Tasks",
        views=("list", "kanban", "form"),
        kanban_group_by="status",
        search_fields=("title",),
        fields=(
            FieldSpec("title", "Title", "text", required=True),
            FieldSpec(
                "project_id", "Project", "reference", reference="projects.project", list_visible=False
            ),
            FieldSpec("status", "Status", "select", options=TASK_STATUSES, required=True),
            FieldSpec("priority", "Priority", "select", options=TASK_PRIORITIES, required=True),
            FieldSpec("assignee_email", "Assignee", "person", reference="/api/projects/tasks/assignable"),
            FieldSpec("assigned_by_name", "Given by", "text", form_visible=False),
            FieldSpec("due_at", "Due", "date"),
            FieldSpec("description", "Description", "textarea", list_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="ticket",
        app="projects",
        label="Ticket",
        label_plural="Helpdesk Tickets",
        views=("list", "kanban", "form"),
        kanban_group_by="status",
        search_fields=("subject", "requester_email"),
        fields=(
            FieldSpec("subject", "Subject", "text", required=True),
            FieldSpec("status", "Status", "select", options=TICKET_STATUSES, required=True),
            FieldSpec("priority", "Priority", "select", options=TICKET_PRIORITIES, required=True),
            FieldSpec("requester_email", "Requester", "email"),
            FieldSpec("customer_id", "Customer", "reference", reference="invoicing.customer", list_visible=False),
            FieldSpec("due_at", "Due", "date"),
            FieldSpec("description", "Description", "textarea", list_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="time_entry",
        app="projects",
        label="Time Entry",
        label_plural="Time Entries",
        views=("list",),
        search_fields=("note",),
        fields=(
            FieldSpec("task_id", "Task", "reference", reference="projects.task", required=True),
            FieldSpec("minutes", "Minutes", "number", required=True),
            FieldSpec("note", "Note", "text"),
            FieldSpec("created_at", "Logged", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-projects")

projects_router = APIRouter(prefix="/projects", tags=["projects"])
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])
time_entries_router = APIRouter(prefix="/time_entries", tags=["time-entries"])
tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])
webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


@projects_router.get("", response_model=list[ProjectOut])
async def list_projects(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Project).where(Project.org_id == _org(principal)).order_by(Project.created_at.desc()))
    return rows.scalars().all()


@projects_router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    project = Project(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@projects_router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    project = await session.get(Project, project_id)
    if project is None or str(project.org_id) != principal.org_id:
        raise HTTPException(404, "project not found")
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field_name, value)
    await session.commit()
    await session.refresh(project)
    return project


# Tasks down the reporting line (HR plan 8.4.2): everyone sees the tasks
# they were given and the ones they gave; team leaders their team's,
# branch managers their locations', owners and admins all. Giving a task
# follows the same line (tasks.assign); staff only give themselves one.


async def _people_over(principal: Principal, scope: Scope | None) -> set[str] | None:
    """Whose tasks `scope` covers (None = everyone's): own, the team (down
    the line), or everyone at the caller's locations plus their team."""
    if scope is None:
        return {principal.user_id}
    who = await people_in(scope, principal.org_id)
    if who is None:
        return None
    return {principal.user_id, *who, *(principal.team if scope.kind == "loc" else ())}


def _mine(principal: Principal):
    """Given to me: by user id, or (tasks from before person links) by email."""
    return or_(
        Task.assignee_user_id == principal.user_id,
        and_(Task.assignee_user_id == "", func.lower(Task.assignee_email) == principal.email.lower()),
    )


async def _assignee(principal: Principal, user_id: str, email: str) -> dict | None:
    """Who a task is for, checked: a member of the business whom the caller
    may give tasks to (themselves, or someone down their line)."""
    user_id, email = (user_id or "").strip(), (email or "").strip()
    if not user_id and not email:
        return None
    if user_id == principal.user_id or (not user_id and email.lower() == principal.email.lower()):
        return {"user_id": principal.user_id, "name": "", "email": principal.email}
    person = await person_in_business(principal.org_id, user_id=user_id, email=email)
    if person is None:
        raise HTTPException(422, "nobody in this business has that email" if email and not user_id else "that person isn't in this business")
    scope = scope_for(principal, "tasks.assign")
    over = await _people_over(principal, scope) if scope and scope.kind != "own" else {principal.user_id}
    if over is not None and person["user_id"] not in over:
        raise HTTPException(
            403, f"{person.get('name') or person['email']} isn't in your team; ask {who_can('tasks.assign', principal.role)}"
        )
    return person


async def _due(org_id: str, due: datetime | None) -> datetime | None:
    """A due date picked as a day (midnight) means that day's close of
    business, 17:00 in the business's time zone; a time is kept as it is."""
    if due is None or (due.hour, due.minute, due.second) != (0, 0, 0):
        return due
    return local_midnight(due.date(), await business_tz(org_id)) + timedelta(hours=17)


async def _my_name(principal: Principal) -> str:
    me = await person_in_business(principal.org_id, user_id=principal.user_id)
    return (me or {}).get("name") or principal.email


async def _tell(event: str, principal_or_org, task: Task, to: list[str], session: AsyncSession, **extra) -> None:
    to = [u for u in dict.fromkeys(to) if u]
    if not to:
        return
    org_id = principal_or_org if isinstance(principal_or_org, str) else principal_or_org.org_id
    await publish_event(
        event,
        org_id,
        {"task_id": str(task.id), "task": task.title, "to_user_ids": to, "assignee_name": task.assignee_name or task.assignee_email, **extra},
        session=session,
    )


@tasks_router.get("", response_model=list[TaskOut])
async def list_tasks(
    project_id: uuid.UUID | None = None,
    mine: bool = False,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("tasks.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """`mine`: only the tasks given to me (Minions' Today)."""
    query = select(Task).where(Task.org_id == _org(principal))
    if mine:
        query = query.where(_mine(principal))
    else:
        who = await _people_over(principal, scope)
        if who is not None:
            query = query.where(or_(Task.assignee_user_id.in_(who), Task.assigned_by_user_id == principal.user_id, _mine(principal)))
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    rows = await session.execute(query.order_by(Task.created_at.desc()))
    return rows.scalars().all()


@tasks_router.get("/assignable")
async def assignable_people(principal: Principal = Depends(get_current_principal)):
    """Whom I may give tasks to (the form's Assignee list): myself and
    whoever is down my line, or anyone."""
    scope = scope_for(principal, "tasks.assign")
    over = await _people_over(principal, scope) if scope and scope.kind != "own" else {principal.user_id}
    return {"anyone": over is None, "user_ids": sorted(over or ())}


@tasks_router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in TASK_STATUSES:
        raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
    if body.priority not in TASK_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {TASK_PRIORITIES}")
    person = await _assignee(principal, body.assignee_user_id, body.assignee_email)
    now = datetime.now(UTC)
    task = Task(org_id=_org(principal), created_at=now, updated_at=now, **body.model_dump(exclude={"assignee_user_id"}))
    task.due_at = await _due(principal.org_id, task.due_at)
    task.assigned_by_user_id = principal.user_id
    for_someone_else = person is not None and person["user_id"] != principal.user_id
    task.assigned_by_name = await _my_name(principal) if for_someone_else else principal.email
    if person:
        task.assignee_user_id, task.assignee_email = person["user_id"], person["email"]
        task.assignee_name = person.get("name") or person["email"]
    if task.status == "done":
        task.done_at = now
    session.add(task)
    await session.flush()
    if for_someone_else:
        await _tell("projects.task.assigned", principal, task, [task.assignee_user_id], session, from_name=task.assigned_by_name)
    await _schedule_due(principal.org_id, task, session)
    await session.commit()
    await session.refresh(task)
    return task


@tasks_router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Whoever gave a task, or anyone over its person, may change it; the
    person it was given to changes its status."""
    task = await session.get(Task, task_id)
    if task is None or str(task.org_id) != principal.org_id:
        raise HTTPException(404, "task not found")
    mine = task.assignee_user_id == principal.user_id or (
        not task.assignee_user_id and task.assignee_email.lower() == principal.email.lower()
    )
    gave = task.assigned_by_user_id == principal.user_id
    assign = scope_for(principal, "tasks.assign")
    # Over the person: someone up their line (not the person themselves),
    # or anyone for an old task that belongs to nobody yet.
    unowned = not (task.assignee_user_id or task.assigned_by_user_id)
    covers = unowned
    if assign and assign.kind != "own" and not mine:
        over = await _people_over(principal, assign)
        covers = covers or over is None or task.assignee_user_id in over
    if not (mine or gave or covers):
        raise HTTPException(404, "task not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in TASK_STATUSES:
        raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
    if "priority" in changes and changes["priority"] not in TASK_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {TASK_PRIORITIES}")
    if not (gave or covers) and set(changes) - {"status"}:
        raise HTTPException(403, "you can change its status; the person who gave it changes the rest")

    new_person = None
    if "assignee_user_id" in changes or "assignee_email" in changes:
        uid, email = changes.pop("assignee_user_id", None) or "", changes.pop("assignee_email", None) or ""
        if uid != task.assignee_user_id and (uid or email.lower() != task.assignee_email.lower()):
            new_person = await _assignee(principal, uid, email)
            task.assignee_user_id = (new_person or {}).get("user_id", "")
            task.assignee_email = (new_person or {}).get("email", "")
            task.assignee_name = (new_person or {}).get("name") or task.assignee_email
            task.overdue_level = 0
    was_done = task.status == "done"
    due_before, person_before = task.due_at, task.assignee_user_id
    for field_name, value in changes.items():
        setattr(task, field_name, value)
    now = datetime.now(UTC)
    if "due_at" in changes:
        task.due_at = await _due(principal.org_id, task.due_at)
        task.overdue_level = 0
    if task.status == "done" and not was_done:
        task.done_at = now
        if task.assigned_by_user_id != principal.user_id:
            await _tell("projects.task.done", principal, task, [task.assigned_by_user_id], session, from_name=await _my_name(principal))
    elif task.status != "done" and was_done:
        task.done_at, task.overdue_level = None, 0
    if new_person and new_person["user_id"] != principal.user_id:
        await _tell("projects.task.assigned", principal, task, [new_person["user_id"]], session, from_name=await _my_name(principal))
    if task.due_at != due_before or task.assignee_user_id != person_before or (was_done and task.status != "done"):
        await _schedule_due(principal.org_id, task, session)
    task.updated_at = now
    await session.commit()
    await session.refresh(task)
    return task


def _utc(at: datetime) -> datetime:
    """Aware, in UTC (a time sent without a zone is UTC, as Postgres reads it)."""
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(UTC)


async def _schedule_due(org_id: str, task: Task, session: AsyncSession, level: int = 1) -> None:
    """Asks the kernel to deliver projects.task.due at the task's due time
    (level 1) or three days later (level 2), instead of anything polling.
    A schedule left behind by a change (new due time, done) is ignored when
    it arrives: the check compares it with the task."""
    if task.due_at is None or not task.assignee_user_id or task.status == "done":
        return
    due = _utc(task.due_at)
    at = due + (timedelta(days=3) if level == 2 else timedelta())
    await publish_event(
        "projects.task.due",
        org_id,
        {"task_id": str(task.id), "due_at": due.isoformat(), "level": level},
        session=session,
        deliver_at=max(at, datetime.now(UTC)),
    )


@webhooks_router.post("/task-due", dependencies=[Depends(require_kernel_token)], status_code=204)
async def task_due(body: dict, session: AsyncSession = Depends(get_session)):
    """A task's due time came (scheduled by _schedule_due). Still open and
    unchanged: on the due day the person and whoever gave it are told,
    three days later the next person up the giver's line (owner default,
    2026-11-25)."""
    org_id, payload = str(body["org_id"]), body.get("payload") or {}
    await set_org_context(session, org_id)
    if not await first_delivery(session, body):
        return
    try:
        task = await session.get(Task, uuid.UUID(str(payload.get("task_id"))), with_for_update=True)
        due = _utc(datetime.fromisoformat(str(payload.get("due_at"))))
        level = int(payload.get("level") or 1)
    except (ValueError, TypeError):
        return
    if (
        task is None
        or str(task.org_id) != org_id
        or task.status == "done"
        or not task.assignee_user_id
        or task.due_at is None
        or _utc(task.due_at) != due
        or task.overdue_level >= level
    ):
        await session.commit()
        return
    if level == 1:
        await _tell("projects.task.overdue", org_id, task, [task.assignee_user_id, task.assigned_by_user_id], session, level=1)
        await _schedule_due(org_id, task, session, level=2)
    else:
        line = await approvers_for(org_id, task.assigned_by_user_id or task.assignee_user_id)
        up = (line.chain or line.top or ({},))[0].get("user_id", "")
        await _tell("projects.task.overdue", org_id, task, [up], session, level=2)
    task.overdue_level = level
    await session.commit()


@tickets_router.get("", response_model=list[TicketOut])
async def list_tickets(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Ticket).where(Ticket.org_id == _org(principal)).order_by(Ticket.created_at.desc()))
    return rows.scalars().all()


@tickets_router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(
    body: TicketCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    now = datetime.now(UTC)
    ticket = Ticket(org_id=_org(principal), created_at=now, updated_at=now, **body.model_dump())
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


@tickets_router.patch("/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    ticket_id: uuid.UUID,
    body: TicketUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or str(ticket.org_id) != principal.org_id:
        raise HTTPException(404, "ticket not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in TICKET_STATUSES:
        raise HTTPException(422, f"status must be one of {TICKET_STATUSES}")
    for field_name, value in changes.items():
        setattr(ticket, field_name, value)
    ticket.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(ticket)
    return ticket


@time_entries_router.get("", response_model=list[TimeEntryOut])
async def list_time_entries(
    task_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    query = select(TimeEntry).where(TimeEntry.org_id == _org(principal))
    if task_id is not None:
        query = query.where(TimeEntry.task_id == task_id)
    rows = await session.execute(query.order_by(TimeEntry.created_at.desc()))
    return rows.scalars().all()


@time_entries_router.post("", response_model=TimeEntryOut, status_code=201)
async def create_time_entry(
    body: TimeEntryCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    task = await session.get(Task, body.task_id)
    if task is None or str(task.org_id) != principal.org_id:
        raise HTTPException(404, "task not found")
    entry = TimeEntry(
        org_id=_org(principal),
        task_id=body.task_id,
        minutes=body.minutes,
        note=body.note,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(tickets_router)
app.include_router(time_entries_router)
app.include_router(webhooks_router)
