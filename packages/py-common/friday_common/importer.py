"""Importing existing records into an app (plan 2.4).

A source (a CSV file, or a table in the customer's old database read
through the kernel) is mapped in the browser to one of an app's import
targets, then sent here in batches. Each row carries the source's own id
(`external_id`); `(org_id, external_source, external_id)` is unique on
every target table, so running the same import again updates the rows it
made instead of duplicating them. Only the columns the person mapped are
written on update, so a re-import never blanks a column Friday filled in
since. Rows made by hand in Friday have no external_id and are never
touched.

    from friday_common.importer import ImportField, ImportTarget, import_router
    app.include_router(import_router([ImportTarget("supplier", "Suppliers", "suppliers", (...))]))
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import Principal, require_role
from .db import get_org_session

FieldKind = Literal["text", "email", "phone", "cents", "int", "bool"]
MAX_ROWS = 500
MAX_TEXT = 500


@dataclass(frozen=True)
class ImportField:
    name: str  # the column; a fixed identifier, never from a request
    label: str
    kind: FieldKind = "text"
    required: bool = False


@dataclass(frozen=True)
class ImportTarget:
    entity: str
    label: str
    table: str
    fields: tuple[ImportField, ...]

    def field(self, name: str) -> ImportField | None:
        return next((f for f in self.fields if f.name == name), None)


class ImportRow(BaseModel):
    external_id: str = Field(min_length=1, max_length=200)
    values: dict[str, Any]


class ImportBatch(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    rows: list[ImportRow] = Field(max_length=MAX_ROWS)


class RowError(BaseModel):
    external_id: str
    message: str


class ImportResult(BaseModel):
    inserted: int
    updated: int
    errors: list[RowError]


_TRUE = {"true", "t", "yes", "y", "1", "on"}
_FALSE = {"false", "f", "no", "n", "0", "off", ""}


def coerce(f: ImportField, raw: Any) -> Any:
    """One source value to the column's type; ValueError says why not."""
    if raw is None:
        raw = ""
    if f.kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ValueError(f"{f.label}: {raw!r} isn't yes or no")
    if f.kind in ("cents", "int"):
        if isinstance(raw, bool):
            raise ValueError(f"{f.label}: {raw!r} isn't a number")
        s = str(raw).strip()
        if s == "":
            return 0
        # "KSh 1,250.50", "$12", "1 250" -> 1250.50; a comma alone as the
        # decimal mark ("12,50") is read as a decimal.
        s = re.sub(r"[^\d,.\-]", "", s)
        if "," in s and "." not in s and re.fullmatch(r"-?\d+,\d{1,2}", s):
            s = s.replace(",", ".")
        s = s.replace(",", "")
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"{f.label}: {raw!r} isn't a number") from None
        if f.kind == "cents":
            return int((d * 100).to_integral_value())
        if d != d.to_integral_value():
            raise ValueError(f"{f.label}: {raw!r} isn't a whole number")
        return int(d)
    s = str(raw).strip()
    if len(s) > MAX_TEXT:
        raise ValueError(f"{f.label}: longer than {MAX_TEXT} characters")
    if f.kind == "email":
        s = s.lower()
        if s and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
            raise ValueError(f"{f.label}: {raw!r} isn't an email address")
    if f.required and s == "":
        raise ValueError(f"{f.label} is empty")
    return s


def import_router(targets: list[ImportTarget]) -> APIRouter:
    by_entity = {t.entity: t for t in targets}
    router = APIRouter(prefix="/import", tags=["import"])

    @router.get("/targets")
    async def list_targets(principal: Principal = Depends(require_role("admin"))):
        return [
            {
                "entity": t.entity,
                "label": t.label,
                "fields": [
                    {"name": f.name, "label": f.label, "kind": f.kind, "required": f.required}
                    for f in t.fields
                ],
            }
            for t in targets
        ]

    @router.post("/{entity}", response_model=ImportResult)
    async def run_import(
        entity: str,
        batch: ImportBatch,
        principal: Principal = Depends(require_role("admin")),
        session: AsyncSession = Depends(get_org_session),
    ):
        if principal.via:
            raise HTTPException(403, "imports are run by a person, not an assistant")
        target = by_entity.get(entity)
        if target is None:
            raise HTTPException(404, f"nothing to import called {entity!r}")
        if not batch.rows:
            return ImportResult(inserted=0, updated=0, errors=[])

        # The mapped columns are the union of what the rows carry; every
        # name must be one of the target's fields (never interpolated
        # otherwise), and the required ones must be mapped.
        mapped: list[ImportField] = []
        for row in batch.rows:
            for name in row.values:
                f = target.field(name)
                if f is None:
                    raise HTTPException(400, f"{target.label} have no field {name!r}")
                if f not in mapped:
                    mapped.append(f)
        missing = [f.label for f in target.fields if f.required and f not in mapped]
        if missing:
            raise HTTPException(400, "map a column to " + ", ".join(missing))

        cols = [f.name for f in mapped]
        insert_cols = ", ".join(["org_id", "external_source", "external_id", *cols])
        params = ", ".join([":org_id", ":source", ":external_id", *(f":v_{c}" for c in cols)])
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        sql = text(
            f"INSERT INTO {target.table} ({insert_cols}) VALUES ({params}) "
            f"ON CONFLICT (org_id, external_source, external_id) DO UPDATE SET {updates} "
            "RETURNING (xmax = 0) AS inserted"
        )

        inserted = updated = 0
        errors: list[RowError] = []
        seen: set[str] = set()
        for row in batch.rows:
            ext = row.external_id.strip()
            if ext in seen:
                errors.append(RowError(external_id=ext, message="this id appears twice in the batch"))
                continue
            seen.add(ext)
            try:
                values = {f"v_{f.name}": coerce(f, row.values.get(f.name)) for f in mapped}
            except ValueError as exc:
                errors.append(RowError(external_id=ext, message=str(exc)))
                continue
            was_insert = (
                await session.execute(
                    sql,
                    {"org_id": principal.org_id, "source": batch.source.strip(), "external_id": ext, **values},
                )
            ).scalar_one()
            if was_insert:
                inserted += 1
            else:
                updated += 1
        await session.commit()
        return ImportResult(inserted=inserted, updated=updated, errors=errors)

    return router
