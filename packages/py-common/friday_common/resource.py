"""The schema-driven UI contract.

This is the single biggest simplification Friday makes relative to a
legacy ERP's view layer: instead of every app hand-building bespoke list,
kanban, and form screens (and a view-inheritance system to let other
modules patch them), an app declares its data shape once as a
`ResourceSpec`. The web shell's generic renderer (`web/src/ui/resource`)
turns that declaration directly into list/kanban/form screens. An app only
writes a custom React screen when the workflow genuinely needs one (the POS
register, a drag-and-drop pipeline board) -- and even those read field
metadata from the same registry so they don't duplicate it.
"""

from dataclasses import dataclass, field
from typing import Literal

FieldType = Literal[
    "text", "textarea", "number", "currency", "boolean", "date",
    "datetime", "select", "reference", "email", "phone",
]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    type: FieldType
    required: bool = False
    options: tuple[str, ...] | None = None  # for type="select"
    reference: str | None = None  # resource name, for type="reference"
    list_visible: bool = True
    form_visible: bool = True


@dataclass(frozen=True)
class ResourceSpec:
    name: str  # e.g. "opportunity" -- unique within the owning app
    app: str  # e.g. "crm"
    label: str
    label_plural: str
    fields: tuple[FieldSpec, ...]
    views: tuple[str, ...] = ("list", "form")
    kanban_group_by: str | None = None  # field name to group kanban columns by
    search_fields: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "app": self.app,
            "label": self.label,
            "labelPlural": self.label_plural,
            "views": list(self.views),
            "kanbanGroupBy": self.kanban_group_by,
            "searchFields": list(self.search_fields),
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "options": list(f.options) if f.options else None,
                    "reference": f.reference,
                    "listVisible": f.list_visible,
                    "formVisible": f.form_visible,
                }
                for f in self.fields
            ],
        }


_REGISTRY: dict[str, ResourceSpec] = {}


def resource(spec: ResourceSpec) -> ResourceSpec:
    """Register a resource so the kernel's app registry and the web shell's
    generic renderer can discover it. Call this once at app startup."""
    _REGISTRY[f"{spec.app}.{spec.name}"] = spec
    return spec


def all_resources() -> list[ResourceSpec]:
    return list(_REGISTRY.values())
