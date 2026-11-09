import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    resource,
)
from sqlalchemy import select
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
            FieldSpec("assignee_email", "Assignee", "email"),
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


@tasks_router.get("", response_model=list[TaskOut])
async def list_tasks(
    project_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    query = select(Task).where(Task.org_id == _org(principal))
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    rows = await session.execute(query.order_by(Task.created_at.desc()))
    return rows.scalars().all()


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
    now = datetime.now(UTC)
    task = Task(org_id=_org(principal), created_at=now, updated_at=now, **body.model_dump())
    session.add(task)
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
    task = await session.get(Task, task_id)
    if task is None or str(task.org_id) != principal.org_id:
        raise HTTPException(404, "task not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in TASK_STATUSES:
        raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
    if "priority" in changes and changes["priority"] not in TASK_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {TASK_PRIORITIES}")
    for field_name, value in changes.items():
        setattr(task, field_name, value)
    task.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)
    return task


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
