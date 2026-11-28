#!/usr/bin/env bash
# Scaffolds a new app in the standard shape (mirrors apps/crm): a FastAPI
# service with one example ResourceSpec, a migration, and a kernel
# registry entry -- so it's navigable from the web launcher with zero
# bespoke frontend code. See CONTRIBUTING.md.
#
# Usage: ./scripts/new-app.sh my_app
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <app_name>  (lowercase, underscores, e.g. my_app)" >&2
    exit 1
fi

name="$1"
if ! [[ "$name" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "app name must be lowercase letters, digits, underscores, starting with a letter" >&2
    exit 1
fi

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir="$root_dir/apps/$name"

if [ -e "$app_dir" ]; then
    echo "apps/$name already exists" >&2
    exit 1
fi

label="$(echo "${name:0:1}" | tr '[:lower:]' '[:upper:]')${name:1}"
label="${label//_/ }"

echo "==> scaffolding apps/$name"
mkdir -p "$app_dir/app" "$app_dir/migrations" "$app_dir/tests"
touch "$app_dir/app/__init__.py"

cat > "$app_dir/pyproject.toml" <<EOF
[tool.ruff]
line-length = 110
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
EOF

cat > "$app_dir/requirements.txt" <<'EOF'
# install from the repo root: pip install -r apps/__NAME__/requirements.txt
-e packages/py-common
fastapi>=0.115
uvicorn[standard]>=0.30
EOF
sed -i "s/__NAME__/$name/" "$app_dir/requirements.txt"

cat > "$app_dir/requirements-dev.txt" <<'EOF'
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.24
httpx>=0.27
ruff>=0.6
EOF

cat > "$app_dir/app/models.py" <<EOF
import uuid

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
EOF

cat > "$app_dir/app/schemas.py" <<EOF
import uuid

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    name: str = Field(min_length=1)


class ItemOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}
EOF

cat > "$app_dir/app/main.py" <<EOF
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_common import FieldSpec, Principal, ResourceSpec, create_app, get_current_principal, get_org_session, resource

from .models import Item
from .schemas import ItemCreate, ItemOut

# Rename/extend this resource for the real domain this app owns -- this is
# just enough to be navigable from the launcher immediately. See
# ARCHITECTURE.md's "schema-driven UI contract" for what ResourceSpec buys
# you: list/kanban/form screens with no React code.
resource(
    ResourceSpec(
        name="item",
        app="$name",
        label="Item",
        label_plural="Items",
        views=("list", "form"),
        search_fields=("name",),
        fields=(FieldSpec("name", "Name", "text", required=True),),
    )
)

app = create_app("friday-$name")
router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemOut])
async def list_items(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Item).where(Item.org_id == uuid.UUID(principal.org_id)))
    return rows.scalars().all()


@router.post("", response_model=ItemOut, status_code=201)
async def create_item(
    body: ItemCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    item = Item(org_id=uuid.UUID(principal.org_id), **body.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


app.include_router(router)
EOF

cat > "$app_dir/migrations/0001_${name}.sql" <<EOF
CREATE TABLE items (
    id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id  UUID NOT NULL,
    name    TEXT NOT NULL
);

CREATE INDEX idx_items_org ON items(org_id);

-- Row-Level Security: see kernel/migrations or apps/crm/migrations for the
-- full explanation. friday_common.get_org_session sets app.current_org_id.
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE items FORCE ROW LEVEL SECURITY;

CREATE POLICY items_org_isolation ON items
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
EOF

echo "==> registering apps/$name with the kernel"
python3 - "$root_dir/kernel/internal/registry/registry.go" "$name" "$label" <<'PY'
import re
import sys

path, name, label = sys.argv[1:4]
src = open(path, encoding="utf-8").read()

entry = (
    "\t\t{{\n"
    "\t\t\tName:        \"{name}\",\n"
    "\t\t\tLabel:       \"{label}\",\n"
    "\t\t\tDescription: \"TODO: describe {label}.\",\n"
    "\t\t\tIcon:        \"app-window\",\n"
    "\t\t\tCategory:    \"other\",\n"
    "\t\t\tBaseURL:     envOr(\"APP_{env}_URL\", \"http://localhost:8004\"),\n"
    "\t\t}},\n"
).format(name=name, label=label, env=name.upper())

marker = "\n\t}\n}\n\nfunc envOr"
if marker not in src:
    print("could not find insertion point in registry.go -- add the entry by hand", file=sys.stderr)
    sys.exit(1)

src = src.replace(marker, "\n" + entry + "\t}\n}\n\nfunc envOr", 1)
open(path, "w", encoding="utf-8").write(src)
PY

cat <<EOF

Scaffolded apps/$name. Next steps:
  1. Pick a real port (the registry entry defaults to 8004 -- bump it if
     another app already uses that) and add it to .env.example / docker-compose.yml.
  2. pip install -r apps/$name/requirements.txt -r apps/$name/requirements-dev.txt
  3. python -m friday_common.migrate apps/$name $name
  4. uvicorn app.main:app --reload --port 8004 --app-dir apps/$name
  5. Replace the example "Item" resource with the real domain model.
EOF
