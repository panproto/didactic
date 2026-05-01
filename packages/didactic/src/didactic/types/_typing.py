"""Central type aliases used throughout didactic.

didactic's coding standard rejects ``typing.Any`` and bare ``object`` in
type hints. The aliases here cover every place where we'd otherwise reach
for one of those: JSON-shape values, didactic field-shape values,
panproto spec payloads, metadata-marker class references, and the
encoded-string form that storage backends carry.

Module conventions
------------------
Every alias is declared with PEP 695 type-alias syntax (``type X = ...``).
Recursive aliases use forward references inside the alias body and are
resolved lazily by the type checker.

See Also
--------
didactic.types._types : the translation layer that consumes these aliases.
"""

# References ``_Missing`` (the sentinel singleton class) by name in
# the ``DefaultOrMissing`` alias; the ``_`` is conventional.
# Tracked in panproto/didactic#1.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, ForwardRef, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from didactic.fields._fields import _Missing
    from didactic.models._model import Model


# ---------------------------------------------------------------------------
# Structural "anything" Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Opaque(Protocol):
    """An opaque object. Every Python value satisfies this Protocol.

    Used in positions where the value is genuinely heterogeneous and we
    will only round-trip it (e.g. ``Annotated[T, ...]`` metadata items
    we don't recognise). Carries no operations beyond identity.

    Notes
    -----
    Prefer a more specific type wherever possible. ``Opaque`` is the
    documented escape hatch for "I take any Python object and only
    inspect it via ``isinstance`` / ``type``".
    """


# ---------------------------------------------------------------------------
# JSON values
# ---------------------------------------------------------------------------

#: Any JSON-encodable value: scalars, lists, and string-keyed objects of
#: itself. Suitable for spec dicts passed to ``panproto.create_theory``,
#: for ``model_dump`` payloads, and for anything else that must be
#: serialisable through ``json.dumps``.
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)

#: Convenience alias for an object-shaped JsonValue (``dict[str, JsonValue]``).
type JsonObject = dict[str, JsonValue]


# ---------------------------------------------------------------------------
# Field-space values
# ---------------------------------------------------------------------------

#: Any value a [Model][didactic.api.Model] field can hold. Recursive: the
#: container variants nest. ``"Model"`` covers ``Embed[T]`` field values.
type FieldValue = (
    str
    | int
    | float
    | bool
    | bytes
    | Decimal
    | datetime
    | date
    | time
    | UUID
    | None
    | tuple[FieldValue, ...]
    | frozenset[FieldValue]
    | dict[str, FieldValue]
    | Model
)


# ---------------------------------------------------------------------------
# Encoded / storage values
# ---------------------------------------------------------------------------

#: The panproto-shape encoded form of every field value. ``str`` is the
#: only inhabitant; the alias exists so callers can read intent at sites
#: where "this is the encoded representation, not arbitrary text" matters.
type Encoded = str


# ---------------------------------------------------------------------------
# Class / forward-reference targets
# ---------------------------------------------------------------------------

#: Targets accepted by [Ref[T]][didactic.api.Ref], [Embed[T]][didactic.api.Embed],
#: and similar markers: a real class, a forward-ref string, or a
#: ``typing.ForwardRef`` proxy.
type ClassTarget = type | str | ForwardRef


# ---------------------------------------------------------------------------
# Field default sentinel
# ---------------------------------------------------------------------------

#: A field default may be either a real value or the
#: [MISSING][didactic.fields._fields.MISSING] sentinel.
type DefaultOrMissing = FieldValue | _Missing


__all__ = [
    "ClassTarget",
    "DefaultOrMissing",
    "Encoded",
    "FieldValue",
    "JsonObject",
    "JsonValue",
    "Opaque",
]
