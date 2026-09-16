"""Text to value: the stdlib scalar grammar and annotation-directed decoding.

Override values, environment variables, dotenv lines and CLI arguments
arrive as text. Two readings are provided: :func:`parse_scalar` is the
schema-free grammar (null, booleans, numbers, JSON lists and objects,
quoted strings, bare words) used where no annotation is at hand, and
:func:`decode_text` reads text for a known leaf annotation, so ``"123"``
stays a string under ``str`` and becomes an integer under ``int``.
"""

from __future__ import annotations

import enum
import json
import re
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Literal, Union, cast, get_args, get_origin

import didactic.api as dx
from didactic.settings._errors import CoercionError, OverrideSyntaxError
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
        otherwise split on commas, decoding each item as ``T``. A map or
        model slot requires JSON object text. Any other annotation falls
        back to :func:`parse_scalar`.

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
    if typ is str:
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
    if head is tuple or head is frozenset:
        return _decode_sequence(text, get_args(typ)[0], path=path, origin=origin)
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
        for piece in stripped.split(",")
    ]


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


__all__ = ["decode_text", "parse_override", "parse_scalar", "validate_override_key"]
