"""Text to value: the stdlib scalar grammar, decoding and the typed check.

Override values, environment variables, dotenv lines and CLI arguments
arrive as text. Two readings are provided: :func:`parse_scalar` is the
schema-free grammar (null, booleans, numbers, JSON lists and objects,
quoted strings, bare words) used where no annotation is at hand, and
:func:`decode_text` reads text for a known leaf annotation, so ``"123"``
stays a string under ``str`` and becomes an integer under ``int``. Values
that arrive already typed (a file, a mapping, a ``(key, value)`` pair)
are checked against the leaf annotation by :func:`check_value`, so a
string where an integer is declared is refused with the leaf's path and
the layer that set it.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath
from types import EllipsisType, NoneType, UnionType
from typing import TYPE_CHECKING, Any, Literal, Union, cast, get_args, get_origin
from uuid import UUID

import didactic.api as dx
from didactic.settings._errors import CoercionError, OverrideSyntaxError
from didactic.settings._interpolation import is_whole_expression, mentions_expression
from didactic.types import unwrap_annotated

if TYPE_CHECKING:
    from didactic.settings._provenance import Origin
    from didactic.settings._values import ConfigValue
    from didactic.types._types import TypeForm

_INT = re.compile(r"[+-]?(0|[1-9][0-9]*)")
_FLOAT = re.compile(
    r"[+-]?(([0-9]+\.[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)"
)
_NAMED_FLOATS = frozenset({"inf", "+inf", "-inf", "nan"})
_NULLS = frozenset({"", "null", "~"})
_BOOLEANS = {"true": True, "false": False}
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def parse_scalar(text: str) -> ConfigValue:
    """Read text with the schema-free grammar.

    Surrounding whitespace is ignored. ``null``, ``~`` and the empty
    string give ``None``; ``true`` and ``false`` (any case) give booleans;
    an integer literal without a leading zero gives an ``int``; a float
    literal (``1.5``, ``1e-3``, ``inf``, ``nan``) gives a ``float``; text
    starting with ``[`` or ``{`` is JSON; a single- or double-quoted
    string gives its contents; anything else is the text itself.

    Raises
    ------
    OverrideSyntaxError
        When text starting with ``[`` or ``{`` is not valid JSON.
    """
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in _NULLS:
        return None
    if lowered in _BOOLEANS:
        return _BOOLEANS[lowered]
    if _INT.fullmatch(stripped):
        return int(stripped)
    if _FLOAT.fullmatch(stripped) or lowered in _NAMED_FLOATS:
        return float(stripped)
    if stripped[0] in "[{":
        return _parse_json(stripped)
    return _unquote(stripped)


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _parse_json(text: str) -> ConfigValue:
    try:
        return cast("ConfigValue", json.loads(text))
    except json.JSONDecodeError as exc:
        msg = f"Value {text!r} is not valid JSON: {exc.msg} at column {exc.colno}"
        raise OverrideSyntaxError(msg) from exc


def parse_override(expr: str) -> tuple[str, str]:
    """Split a ``key=value`` override into its key and raw value text.

    The key is validated: it must be non-empty, every dotted segment must
    be non-empty, and no segment may be an integer (lists are set whole,
    as ``tags=[...]``). The value text is returned untouched; the leaf
    annotation decides how it is read.

    Raises
    ------
    OverrideSyntaxError
        When ``=`` is absent or the key is malformed.
    """
    if "=" not in expr:
        msg = f"Override {expr!r} is missing '='; expected key=value"
        raise OverrideSyntaxError(msg)
    key, _, value = expr.partition("=")
    key = key.strip()
    if not key:
        msg = f"Override {expr!r} has an empty key; expected key=value"
        raise OverrideSyntaxError(msg)
    validate_override_key(key)
    return key, value


def validate_override_key(key: str) -> None:
    """Check a dotted override key.

    Every segment must be non-empty and no segment may be an integer,
    since lists are set whole rather than indexed into.

    Raises
    ------
    OverrideSyntaxError
        When the key is malformed.
    """
    if not key:
        msg = "Override key is empty; expected a dotted path"
        raise OverrideSyntaxError(msg)
    segments = key.split(".")
    for index, segment in enumerate(segments):
        if not segment:
            msg = f"Override key {key!r} has an empty segment"
            raise OverrideSyntaxError(msg)
        if _INT.fullmatch(segment):
            head = ".".join(segments[:index])
            msg = (
                f"Override key {key!r} indexes into a list; "
                f"lists are set whole, as {head}=[...]"
            )
            raise OverrideSyntaxError(msg)


def decode_text(
    text: str,
    annotation: object,
    *,
    path: str,
    origin: Origin | None = None,
) -> ConfigValue:
    """Read text for a leaf annotation.

    Parameters
    ----------
    text
        The text as it arrived from the environment, a dotenv file, the
        command line or an override string.
    annotation
        The leaf's annotation (``FieldSpec.annotation``, or the value type
        of a ``dict[str, T]`` entry). ``Annotated[T, ...]`` unwraps to
        ``T`` and ``T | None`` reads ``null``, ``~`` and the empty string
        as ``None`` before decoding ``T``.
    path
        Dotted path of the leaf, for the error message.
    origin
        The layer that supplied the text, for the error message.

    Returns
    -------
    ConfigValue
        ``str`` keeps the text verbatim. ``bool`` accepts ``1``, ``0``,
        ``true``, ``false``, ``yes``, ``no``, ``on`` and ``off`` in any
        case. ``int`` and ``float`` use the constructors. ``Literal[...]``
        matches the text against ``str()`` of each member and returns the
        member. An ``Enum`` is matched by member name, then by value, and
        the member's value is returned. ``tuple[T, ...]`` and
        ``frozenset[T]`` read JSON when the text starts with ``[`` and
        otherwise split on commas outside brackets, braces and quotes,
        decoding each item as ``T``. A map or model slot requires JSON
        object text. Any other annotation falls back to
        :func:`parse_scalar`. Text holding a ``${...}`` expression is
        returned as it is, whatever the annotation, so interpolation can
        resolve it; the resolved value is checked against the annotation
        afterwards.

    Raises
    ------
    CoercionError
        When the text cannot be read for the annotation.
    """
    base, _ = unwrap_annotated(cast("TypeForm", annotation))
    return _decode(text, base, path=path, origin=origin)


def _decode(text: str, typ: object, *, path: str, origin: Origin | None) -> ConfigValue:
    typ, _ = unwrap_annotated(cast("TypeForm", typ))
    head = get_origin(typ)
    if head is Union or head is UnionType:
        return _decode_union(text, get_args(typ), path=path, origin=origin)
    if (head is tuple or head is frozenset) and not is_whole_expression(text):
        return _decode_sequence(text, get_args(typ)[0], path=path, origin=origin)
    if typ is str or mentions_expression(text):
        return text
    if typ is bool:
        return _decode_bool(text, path=path, origin=origin)
    if typ is int or typ is float:
        return _decode_number(text, typ, path=path, origin=origin)
    return _decode_structured(text, typ, head, path=path, origin=origin)


def _decode_union(
    text: str, members: tuple[object, ...], *, path: str, origin: Origin | None
) -> ConfigValue:
    inner = [member for member in members if member is not NoneType]
    if len(inner) < len(members) and text.strip().lower() in _NULLS:
        return None
    if len(inner) == 1:
        return _decode(text, inner[0], path=path, origin=origin)
    return parse_scalar(text)


def _decode_structured(
    text: str, typ: object, head: object, *, path: str, origin: Origin | None
) -> ConfigValue:
    if head is Literal:
        return _decode_literal(text, get_args(typ), path=path, origin=origin)
    enum_class = _enum_class(typ)
    if enum_class is not None:
        return _decode_enum(text, enum_class, path=path, origin=origin)
    if head is dict or _is_model(typ):
        stripped = text.strip()
        if stripped.startswith("{"):
            return _parse_json(stripped)
        expected = f"JSON object text for {_render(typ)}"
        raise _refused(text, expected, path, origin)
    return parse_scalar(text)


def _is_model(typ: object) -> bool:
    return isinstance(typ, type) and issubclass(typ, dx.Model)


def _enum_class(typ: object) -> type[enum.Enum] | None:
    if isinstance(typ, type) and issubclass(typ, enum.Enum):
        return typ
    return None


def _decode_bool(text: str, *, path: str, origin: Origin | None) -> bool:
    lowered = text.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise _refused(text, "bool", path, origin)


def _decode_number(
    text: str,
    kind: type[int] | type[float],
    *,
    path: str,
    origin: Origin | None,
) -> int | float:
    try:
        return kind(text.strip())
    except ValueError:
        raise _refused(text, kind.__name__, path, origin) from None


def _decode_literal(
    text: str,
    members: tuple[object, ...],
    *,
    path: str,
    origin: Origin | None,
) -> ConfigValue:
    stripped = text.strip()
    for member in members:
        if str(member) == stripped or (
            isinstance(member, bool) and str(member).lower() == stripped.lower()
        ):
            return cast("ConfigValue", member)
    expected = "one of [" + ", ".join(repr(m) for m in members) + "]"
    raise _refused(text, expected, path, origin)


def _decode_enum(
    text: str,
    kind: type[enum.Enum],
    *,
    path: str,
    origin: Origin | None,
) -> ConfigValue:
    stripped = text.strip()
    member: enum.Enum | None = kind.__members__.get(stripped)
    if member is None:
        for candidate in kind:
            if str(candidate.value) == stripped:
                member = candidate
                break
    if member is None:
        raise _refused(text, kind.__name__, path, origin)
    return cast("ConfigValue", member.value)


def _decode_sequence(
    text: str, item: object, *, path: str, origin: Origin | None
) -> ConfigValue:
    stripped = text.strip()
    if stripped.startswith("["):
        return _parse_json(stripped)
    if not stripped:
        return []
    return [
        _decode(piece.strip(), item, path=path, origin=origin)
        for piece in split_items(stripped)
    ]


_CLOSERS = {"[": "]", "{": "}", "(": ")"}


def split_items(text: str) -> list[str]:
    """Split text on the commas outside brackets, braces, parentheses and quotes.

    ``a,[1,2],"x,y",${oc.select:p,d}`` gives four items: the comma inside
    a bracketed group, a quoted string or a ``${...}`` expression does
    not separate.
    """
    items: list[str] = []
    depth: list[str] = []
    quote: str | None = None
    start = 0
    for index, char in enumerate(text):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in _CLOSERS:
            depth.append(_CLOSERS[char])
        elif depth and char == depth[-1]:
            depth.pop()
        elif char == "," and not depth:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def _refused(
    text: str, expected: str, path: str, origin: Origin | None
) -> CoercionError:
    where = f" (set by {origin.label})" if origin is not None else ""
    msg = f"Config key {path!r} expects {expected}{where}; got {text!r}"
    return CoercionError(msg, path=path, expected=expected, text=text)


def _render(typ: object) -> str:
    name = getattr(typ, "__name__", None)
    if isinstance(typ, type) and isinstance(name, str):
        return name
    return repr(typ).replace("typing.", "")


def render_annotation(annotation: object) -> str:
    """Render an annotation the way error messages name it.

    A class is named by ``__name__``; every other form (a union, a
    literal, a parameterised container) by its ``repr`` with the
    ``typing.`` prefix dropped.
    """
    return _render(annotation)


def check_value(
    value: ConfigValue,
    annotation: object,
    *,
    path: str,
    origin: Origin | None = None,
) -> None:
    """Refuse a typed value the leaf annotation does not admit.

    Parameters
    ----------
    value
        The value as a file, a mapping, a ``(key, value)`` pair, a
        resolver or a settings source supplied it.
    annotation
        The leaf's annotation, read as :func:`decode_text` reads it.
    path
        Dotted path of the leaf, for the error message.
    origin
        The layer that set the value, for the error message.

    Raises
    ------
    CoercionError
        When the value does not inhabit the annotation: ``bool`` never
        satisfies ``int``, ``int`` satisfies ``float``, ``None`` needs an
        optional annotation, a ``Literal`` or ``Enum`` needs a member (or
        a member's value) of the same type, a ``Path``, ``datetime``,
        ``date``, ``time``, ``UUID``, ``Decimal`` or ``bytes`` leaf takes
        its JSON text form, and a list or mapping is checked element by
        element. A string holding a ``${...}`` expression is admitted
        everywhere and checked again once resolved; an annotation the
        engine does not know (``Any``, a protocol, a type variable) admits
        every value.
    """
    if admits(value, annotation):
        return
    expected = render_annotation(_unwrap(annotation))
    where = f" (set by {origin.label})" if origin is not None else ""
    got = _kind(value) if isinstance(value, Mapping | list | tuple) else repr(value)
    msg = f"Config key {path!r} expects {expected}{where}; got {got}"
    raise CoercionError(msg, path=path, expected=expected, text=got)


def _kind(value: object) -> str:
    return "null" if value is None else type(value).__name__


def _unwrap(annotation: object) -> object:
    base, _ = unwrap_annotated(cast("TypeForm", annotation))
    return base


def admits(value: object, annotation: object) -> bool:
    """Whether a typed value inhabits an annotation, as :func:`check_value` reads it."""
    return _admits(value, annotation)


def _admits(value: object, annotation: object) -> bool:
    if isinstance(value, str) and mentions_expression(value):
        return True
    typ = _unwrap(annotation)
    if typ is Any or typ is object:
        return True
    head = get_origin(typ)
    if head is Union or head is UnionType:
        return any(_admits(value, member) for member in get_args(typ))
    if head is Literal:
        return any(_same(member, value) for member in get_args(typ))
    if head is None and isinstance(typ, type):
        return _admits_class(value, typ)
    return _admits_generic(value, typ, head, get_args(typ))


def _admits_generic(
    value: object, typ: object, head: object, args: tuple[object, ...]
) -> bool:
    if typ is None:
        return value is None
    if head is dict or head is Mapping:
        return _admits_mapping(value, args)
    if head is tuple:
        return _admits_tuple(value, args)
    if head is list or head is frozenset or head is set or head is Sequence:
        return _admits_items(value, args[0] if args else Any)
    return True


def _same(member: object, value: object) -> bool:
    return type(member) is type(value) and member == value


def _is_container(value: object) -> bool:
    return isinstance(value, list | tuple | set | frozenset)


_EXACT_CLASSES: dict[type, Callable[[object], bool]] = {
    NoneType: lambda v: v is None,
    bool: lambda v: isinstance(v, bool),
    int: lambda v: isinstance(v, int) and not isinstance(v, bool),
    float: lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    str: lambda v: isinstance(v, str),
    bytes: lambda v: isinstance(v, str | bytes),
    dict: lambda v: isinstance(v, Mapping),
    list: _is_container,
    tuple: _is_container,
    set: _is_container,
    frozenset: _is_container,
}
"""What a value must be for a bare class annotation."""


def _admits_class(value: object, typ: type) -> bool:
    exact = _EXACT_CLASSES.get(typ)
    if exact is not None:
        return exact(value)
    if issubclass(typ, enum.Enum):
        return isinstance(value, typ) or any(
            _same(member.value, value) for member in typ
        )
    if issubclass(typ, Decimal):
        return isinstance(value, str | int | float | Decimal) and not isinstance(
            value, bool
        )
    if issubclass(typ, datetime | date | time | PurePath | UUID):
        return isinstance(value, str | typ)
    if issubclass(typ, dx.Model):
        return isinstance(value, Mapping | typ)
    return True


def _admits_mapping(value: object, args: tuple[object, ...]) -> bool:
    if not isinstance(value, Mapping):
        return False
    entries = cast("Mapping[object, object]", value)
    item = args[1] if len(args) == 2 else Any
    return all(_admits(entry, item) for entry in entries.values())


def _admits_tuple(value: object, args: tuple[object, ...]) -> bool:
    if len(args) == 2 and isinstance(args[1], EllipsisType):
        return _admits_items(value, args[0])
    if not isinstance(value, list | tuple):
        return False
    items = cast("Sequence[object]", value)
    if not args:
        return True
    return len(items) == len(args) and all(
        _admits(item, arg) for item, arg in zip(items, args, strict=True)
    )


def _admits_items(value: object, item: object) -> bool:
    if not isinstance(value, list | tuple | set | frozenset):
        return False
    items = cast("Sequence[object] | set[object] | frozenset[object]", value)
    return all(_admits(element, item) for element in items)


__all__ = [
    "admits",
    "check_value",
    "decode_text",
    "parse_override",
    "parse_scalar",
    "render_annotation",
    "split_items",
    "validate_override_key",
]
