"""Compatibility classification for indexed Model fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from didactic.gadt._indexed import indexed_marker

if TYPE_CHECKING:
    from didactic.models._model import Model
    from didactic.types._typing import JsonObject, JsonValue


def indexed_signature(cls: type[Model]) -> JsonObject:
    """Return the stable, JSON-shaped indexed contract of a Model."""
    fields: dict[str, JsonValue] = {}
    for field_name, spec in cls.__field_specs__.items():
        marker = indexed_marker(spec)
        if marker is None:
            continue
        fields[field_name] = {
            "family": marker.family.name,
            "indices": list(marker.index_fields),
            "cases": [
                {
                    "indices": [term.to_spec() for term in indices],
                    "python_type": _type_label(annotation),
                }
                for indices, annotation in marker.cases
            ],
            "case_labels": [list(labels) for labels in marker.case_labels],
            "theory": marker.family.owner.to_spec(),
        }
    return {"fields": fields}


def indexed_changes(old: type[Model], new: type[Model]) -> list[JsonObject]:
    """Return conservative breaking changes in indexed contracts."""
    old_fields = cast("dict[str, JsonValue]", indexed_signature(old)["fields"])
    new_fields = cast("dict[str, JsonValue]", indexed_signature(new)["fields"])
    changes: list[JsonObject] = []
    for field_name in sorted(old_fields.keys() | new_fields.keys()):
        before = old_fields.get(field_name)
        after = new_fields.get(field_name)
        if before == after:
            continue
        changes.append(
            {
                "IndexedFamilyChanged": {
                    "field": field_name,
                    "before": before,
                    "after": after,
                }
            }
        )
    return changes


def _type_label(annotation: object) -> str:
    """Return a deterministic public label for a Python annotation."""
    module = getattr(annotation, "__module__", None)
    qualname = getattr(annotation, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return repr(annotation).replace("typing.", "")


__all__ = [
    "indexed_changes",
    "indexed_signature",
]
