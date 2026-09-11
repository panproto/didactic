"""JSON Schema (Draft 2020-12) generation from a Model class.

The single user-facing entry point is
[json_schema_of][didactic.codegen.json_schema_of] (also reachable as
``Model.model_json_schema()``). It walks the Model's
``__field_specs__`` and emits a JSON Schema document that mirrors
Pydantic's output where possible, while also propagating
``annotated-types`` constraints.

Notes
-----
The emitter ships in pure Python rather than going through panproto's
``IoRegistry`` ``json_schema`` codec because Pydantic-shaped consumers
expect very specific dialect details (the way ``$defs`` are named,
where ``description`` lands, which ``format`` strings appear). Using
panproto here would lock didactic to whatever dialect panproto's
codec emits; doing it ourselves lets us track Pydantic byte-for-byte
where it matters.

See Also
--------
didactic.Model.model_json_schema : the conventional entry point.
"""

from __future__ import annotations

from types import NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    NotRequired,
    Required,
    TypedDict,
    Union,
    cast,
    get_args,
    get_origin,
)

from didactic.types._typing import JsonValue

if TYPE_CHECKING:
    from didactic.fields._fields import FieldSpec
    from didactic.models._model import Model
    from didactic.types._typing import Opaque


class JsonSchemaProperty(TypedDict, total=False):
    """A single per-field entry in a JSON Schema document.

    ``type`` is always present (every field has a JSON Schema type);
    everything else is optional and only set when the field carries
    the relevant metadata or constraint. Extension keys (``x-...``)
    and arbitrary ``json_schema_extra`` payloads are not modelled
    here; the implementation builds a plain dict and casts to this
    type at the boundary so dynamic extras still work at runtime.
    """

    type: Required[str]
    format: str
    description: str
    examples: list[JsonValue]
    deprecated: bool
    minimum: JsonValue
    maximum: JsonValue
    exclusiveMinimum: JsonValue
    exclusiveMaximum: JsonValue
    minLength: int
    maxLength: int
    multipleOf: JsonValue
    const: JsonValue
    enum: list[JsonValue]
    anyOf: list[JsonSchemaProperty]
    items: JsonSchemaProperty
    prefixItems: list[JsonSchemaProperty]
    minItems: int
    maxItems: int
    x_didactic_indexed_family: str


# ``$schema`` has a leading ``$`` so the alternative TypedDict
# constructor form is required (the ``class`` form rejects keys that
# are not valid Python identifiers).
JsonSchemaDoc = TypedDict(
    "JsonSchemaDoc",
    {
        "$schema": str,
        "title": str,
        "type": str,
        "properties": dict[str, JsonSchemaProperty],
        "description": NotRequired[str],
        "required": NotRequired[list[str]],
        "allOf": NotRequired[list[dict[str, JsonValue]]],
    },
)

# scalar Python type -> JSON Schema "type"
_PRIMITIVE_TYPE_MAP: dict[type, tuple[str, str | None]] = {
    str: ("string", None),
    int: ("integer", None),
    float: ("number", None),
    bool: ("boolean", None),
    bytes: ("string", "byte"),
}


def json_schema_of(cls: type[Model]) -> JsonSchemaDoc:
    """Build a JSON Schema (Draft 2020-12) document for ``cls``.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    dict
        A JSON Schema object with ``$schema``, ``title``, ``type``,
        ``properties``, ``required``, and (if any fields have
        constraints) per-property ``minimum`` / ``maximum`` / etc.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class User(dx.Model):
    ...     id: str
    ...     age: int = 0
    >>> schema = json_schema_of(User)
    >>> schema["properties"]["id"]["type"]
    'string'
    >>> "id" in schema["required"]
    True
    >>> "age" in schema["required"]
    False
    """
    properties: dict[str, JsonSchemaProperty] = {}
    required: list[str] = []

    for name, spec in cls.__field_specs__.items():
        properties[name] = _schema_for_field(spec)
        if spec.is_required:
            required.append(name)

    schema: JsonSchemaDoc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": cls.__name__,
        "type": "object",
        "properties": properties,
    }
    if cls.__doc__:
        schema["description"] = cls.__doc__.strip()
    if required:
        schema["required"] = required
    conditions = _indexed_conditions(cls)
    if conditions:
        schema["allOf"] = conditions
    return schema


def _schema_for_field(spec: FieldSpec) -> JsonSchemaProperty:
    """Build the per-field property entry.

    Built up as a plain dict and cast to ``JsonSchemaProperty`` at
    return so that arbitrary ``json_schema_extra`` keys (and
    extension keys like ``x-didactic-predicate``) merge cleanly even
    though the TypedDict only enumerates the documented set.
    """
    annotation = spec.annotation
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    out = cast("dict[str, JsonValue]", dict(_schema_for_annotation(annotation)))

    if spec.description:
        out["description"] = spec.description
    if spec.examples:
        # ``spec.examples`` is ``tuple[FieldValue, ...]``; the JSON
        # Schema dialect accepts the JSON-shape subset, so we widen
        # to ``list[JsonValue]`` at the boundary.
        out["examples"] = cast("list[JsonValue]", list(spec.examples))
    if spec.deprecated:
        out["deprecated"] = True

    # propagate annotated-types constraints emitted as axioms, plus
    # any extras carrying explicit json_schema_extra metadata
    extras = dict(spec.extras) if spec.extras else {}
    explicit = extras.pop("json_schema_extra", None)
    if isinstance(explicit, dict):
        out.update(cast("dict[str, JsonValue]", explicit))

    # fold annotated-types primitives we recognise on
    # ``extras["annotated_metadata"]``. The metadata sequence is typed
    # as ``Opaque`` (a marker Protocol); we narrow with isinstance.
    metadata = extras.get("annotated_metadata", ()) or ()
    if isinstance(metadata, (tuple, list)):
        for entry in cast("tuple[Opaque, ...] | list[Opaque]", metadata):
            _apply_annotated_constraint(out, entry)

    return cast("JsonSchemaProperty", out)


def _indexed_conditions(cls: type[Model]) -> list[dict[str, JsonValue]]:
    """Emit conditional schemas that preserve each indexed dependency."""
    from didactic.gadt._indexed import indexed_marker  # noqa: PLC0415

    conditions: list[dict[str, JsonValue]] = []
    for field_name, field_spec in cls.__field_specs__.items():
        marker = indexed_marker(field_spec)
        if marker is None:
            continue
        for case_number, (indices, annotation) in enumerate(marker.cases):
            index_properties: dict[str, JsonValue] = {}
            labels = marker.case_labels[case_number] if marker.case_labels else None
            for index_number, (index_name, index_term) in enumerate(
                zip(marker.index_fields, indices, strict=True)
            ):
                value = (
                    labels[index_number]
                    if labels is not None
                    else _index_json(index_term)
                )
                index_properties[index_name] = {"const": value}
            conditions.append(
                {
                    "if": {
                        "properties": index_properties,
                        "required": list(marker.index_fields),
                    },
                    "then": {
                        "properties": {
                            field_name: cast(
                                "JsonValue", _schema_for_annotation(annotation)
                            )
                        }
                    },
                }
            )
    return conditions


def _index_json(term: object) -> JsonValue:
    """Flatten a nullary code to its discriminator and preserve other terms."""
    from didactic.gadt import App, Term  # noqa: PLC0415

    if isinstance(term, App) and not term.args:
        return term.op
    if isinstance(term, Term):
        return term.to_spec()
    raise TypeError(f"index case must be a GADT Term, got {type(term).__name__}")


def _schema_for_annotation(annotation: object) -> JsonSchemaProperty:
    """Translate the Python shapes admitted by indexed payload cases."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _schema_for_annotation(get_args(annotation)[0])
    if annotation is NoneType:
        return JsonSchemaProperty(type="null")
    if isinstance(annotation, type):
        type_str, format_str = _PRIMITIVE_TYPE_MAP.get(annotation, ("string", None))
        result = JsonSchemaProperty(type=type_str)
        if format_str is not None:
            result["format"] = format_str
        return result
    args = get_args(annotation)
    if origin in {Union, UnionType}:
        return cast(
            "JsonSchemaProperty",
            {"anyOf": [_schema_for_annotation(item) for item in args]},
        )
    if origin is Literal:
        values = cast("tuple[JsonValue, ...]", args)
        return cast("JsonSchemaProperty", {"enum": list(values)})
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return JsonSchemaProperty(
                type="array",
                items=_schema_for_annotation(args[0]),
            )
        return JsonSchemaProperty(
            type="array",
            prefixItems=[_schema_for_annotation(item) for item in args],
            minItems=len(args),
            maxItems=len(args),
        )
    return JsonSchemaProperty(type="string")


def _apply_annotated_constraint(out: dict[str, JsonValue], marker: Opaque) -> None:
    """Translate an ``annotated-types`` marker into a JSON Schema field.

    Marker is duck-typed (``Ge``/``Le``/``MinLen``/etc. share no common
    base class); ``Opaque`` is the project's "any value, narrow at use
    site" Protocol.
    """
    cls_name = type(marker).__name__
    # support the standard annotated-types primitives by attribute name
    # so we don't have to import the package directly
    if cls_name == "Ge":
        out["minimum"] = getattr(marker, "ge", None)
    elif cls_name == "Gt":
        out["exclusiveMinimum"] = getattr(marker, "gt", None)
    elif cls_name == "Le":
        out["maximum"] = getattr(marker, "le", None)
    elif cls_name == "Lt":
        out["exclusiveMaximum"] = getattr(marker, "lt", None)
    elif cls_name == "MinLen":
        out["minLength"] = getattr(marker, "min_length", None)
    elif cls_name == "MaxLen":
        out["maxLength"] = getattr(marker, "max_length", None)
    elif cls_name == "MultipleOf":
        out["multipleOf"] = getattr(marker, "multiple_of", None)
    elif cls_name == "Predicate":
        # predicate constraints have no JSON Schema equivalent; preserve
        # the function repr in a private extension keyword
        out.setdefault("x-didactic-predicate", str(marker))


__all__ = [
    "json_schema_of",
]
