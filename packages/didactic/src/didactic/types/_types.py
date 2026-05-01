"""Translation between Python type hints and panproto theory sorts.

This module is the foundation of the metaclass pipeline (see
[didactic.models._meta][]). It classifies a Python annotation, names the
corresponding panproto sort, and produces an encoder/decoder pair that
maps between Python values and panproto's string-encoded constraint
values.

Module conventions
------------------
Every public function takes a *resolved* annotation; never a string,
never a deferred ``ForwardRef``. The metaclass is responsible for
resolving forward references through ``annotationlib.get_annotations``
before calling into this module.

Notes
-----
Container types (``tuple``, ``frozenset``, ``dict``) recurse to extract
their element-type sorts; the resulting "sort string" is a panproto-side
descriptor like ``"List Int"`` or ``"Map String String"`` that
``panproto.SchemaBuilder.constraint`` accepts.

See Also
--------
didactic.fields._fields : the FieldSpec layer that consumes these encoders.
didactic.models._meta : the metaclass that orchestrates field translation.
"""

# An ``items()`` over an ``Annotated``-stripped value whose type
# narrows to the wider ``object`` carve-out branch.
# Tracked in panproto/didactic#1.
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from functools import reduce
from types import EllipsisType, NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
)
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.types._typing import Encoded, FieldValue, JsonValue, Opaque

# The widest annotation form ``classify`` accepts. Includes the nominal
# ``type`` (covering bare classes and pyright's special-cased parameterised
# generics like ``tuple[int, ...]`` and ``dict[str, int]``) plus PEP 604
# ``UnionType`` (``int | None``), which pyright does *not* narrow to
# ``type``. Other typing special forms — ``typing.Union[...]``,
# ``Annotated[...]``, PEP 695 type aliases — are accepted at runtime but
# fall outside this static union; callers that pass them rely on pyright's
# legacy structural acceptance of those forms.
TypeForm = type | UnionType

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeTranslation:
    """The result of classifying a Python type hint.

    Parameters
    ----------
    sort
        The panproto sort name (e.g. ``"String"``, ``"List Int"``,
        ``"Maybe Decimal"``). Suitable for passing to
        ``panproto.SchemaBuilder.constraint(vertex_id, sort, value)``.
    encode
        Callable mapping a Python value to the panproto string-encoded form.
    decode
        Callable mapping a panproto string-encoded form back to Python.
    is_optional
        ``True`` if the original annotation was ``T | None``.
    inner_kind
        Coarse classification of the underlying Python type. One of:
        ``"scalar"``, ``"list"``, ``"set"``, ``"map"``, ``"tuple"``,
        ``"enum"``, ``"refinement"``.

    See Also
    --------
    classify : entry point that produces a TypeTranslation.
    """

    sort: str
    encode: Callable[[FieldValue], Encoded]
    decode: Callable[[Encoded], FieldValue]
    is_optional: bool = False
    inner_kind: str = "scalar"
    from_json: Callable[[JsonValue], FieldValue] = field(
        default_factory=lambda: _scalar_identity
    )
    """Re-coerce a JSON-decoded value back into the Python-native form.

    JSON's value space is a strict subset of Python's, so a value like
    ``datetime`` or ``Decimal`` becomes a string after :func:`json.dumps`.
    The encoder expects the original Python type, so during JSON loading
    we route the decoded value through ``from_json`` first.

    Default identity (``lambda v: v``) is correct for ``str``, ``int``,
    ``float``, ``bool``, and ``None``; values that JSON natively
    represents.
    """


class TypeNotSupportedError(TypeError):
    """Raised when a Python type cannot be translated to a panproto sort."""


# ---------------------------------------------------------------------------
# Scalar registry
# ---------------------------------------------------------------------------

# Each entry: (sort name, encoder, decoder, from_json).
# ``from_json`` re-coerces the JSON-decoded form back into the Python-native
# type the encoder expects. For types JSON represents natively
# (str/int/float/bool/None) this is the identity.


def _scalar_identity(v: JsonValue) -> FieldValue:
    """Identity function for scalars whose JSON form matches Python's.

    Only invoked on values whose runtime type is one of the scalar
    overlaps between ``JsonValue`` and ``FieldValue``: ``str``, ``int``,
    ``float``, ``bool``, or ``None``. Asserted to keep the static type
    checker on the same page as the registry's intent.
    """
    assert v is None or isinstance(v, (str, int, float, bool))
    return v


# Typed per-scalar encoders/decoders. Pyright's union inference is too
# wide on lambdas closed over ``FieldValue``; declaring each adapter
# with a narrow parameter type keeps the registry's value-type tuple
# precise.
def _enc_str(v: FieldValue) -> Encoded:
    assert isinstance(v, str)
    return v


def _dec_str(s: Encoded) -> FieldValue:
    return s


def _enc_int(v: FieldValue) -> Encoded:
    assert isinstance(v, int) and not isinstance(v, bool)
    return str(v)


def _dec_int(s: Encoded) -> FieldValue:
    return int(s)


def _enc_float(v: FieldValue) -> Encoded:
    assert isinstance(v, (int, float)) and not isinstance(v, bool)
    return repr(float(v))


def _dec_float(s: Encoded) -> FieldValue:
    return float(s)


def _enc_bool(v: FieldValue) -> Encoded:
    assert isinstance(v, bool)
    return "true" if v else "false"


def _dec_bool(s: Encoded) -> FieldValue:
    return s == "true"


def _enc_bytes(v: FieldValue) -> Encoded:
    assert isinstance(v, bytes)
    return v.hex()


def _dec_bytes(s: Encoded) -> FieldValue:
    return bytes.fromhex(s)


def _from_json_bytes(v: JsonValue) -> FieldValue:
    assert isinstance(v, str)
    return bytes.fromhex(v)


def _enc_decimal(v: FieldValue) -> Encoded:
    assert isinstance(v, Decimal)
    return str(v)


def _dec_decimal(s: Encoded) -> FieldValue:
    return Decimal(s)


def _from_json_decimal(v: JsonValue) -> FieldValue:
    assert isinstance(v, (str, int, float)) and not isinstance(v, bool)
    return Decimal(str(v))


def _enc_datetime(v: FieldValue) -> Encoded:
    assert isinstance(v, datetime)
    return v.isoformat()


def _dec_datetime(s: Encoded) -> FieldValue:
    return datetime.fromisoformat(s)


def _from_json_datetime(v: JsonValue) -> FieldValue:
    assert isinstance(v, str)
    return datetime.fromisoformat(v)


def _enc_date(v: FieldValue) -> Encoded:
    assert isinstance(v, date)
    return v.isoformat()


def _dec_date(s: Encoded) -> FieldValue:
    return date.fromisoformat(s)


def _from_json_date(v: JsonValue) -> FieldValue:
    assert isinstance(v, str)
    return date.fromisoformat(v)


def _enc_time(v: FieldValue) -> Encoded:
    assert isinstance(v, time)
    return v.isoformat()


def _dec_time(s: Encoded) -> FieldValue:
    return time.fromisoformat(s)


def _from_json_time(v: JsonValue) -> FieldValue:
    assert isinstance(v, str)
    return time.fromisoformat(v)


def _enc_uuid(v: FieldValue) -> Encoded:
    assert isinstance(v, UUID)
    return str(v)


def _dec_uuid(s: Encoded) -> FieldValue:
    return UUID(s)


def _from_json_uuid(v: JsonValue) -> FieldValue:
    assert isinstance(v, str)
    return UUID(v)


_SCALARS: dict[
    type,
    tuple[
        str,
        Callable[[FieldValue], Encoded],
        Callable[[Encoded], FieldValue],
        Callable[[JsonValue], FieldValue],
    ],
] = {
    str: ("String", _enc_str, _dec_str, _scalar_identity),
    int: ("Int", _enc_int, _dec_int, _scalar_identity),
    float: ("Float64", _enc_float, _dec_float, _scalar_identity),
    bool: ("Bool", _enc_bool, _dec_bool, _scalar_identity),
    bytes: ("Bytes", _enc_bytes, _dec_bytes, _from_json_bytes),
    Decimal: ("Decimal", _enc_decimal, _dec_decimal, _from_json_decimal),
    datetime: ("DateTime", _enc_datetime, _dec_datetime, _from_json_datetime),
    date: ("Date", _enc_date, _dec_date, _from_json_date),
    time: ("Time", _enc_time, _dec_time, _from_json_time),
    UUID: ("Uuid", _enc_uuid, _dec_uuid, _from_json_uuid),
}


def _is_scalar(typ: TypeForm) -> bool:
    return isinstance(typ, type) and typ in _SCALARS


def _scalar_translation(typ: type) -> TypeTranslation:
    sort, enc, dec, from_json = _SCALARS[typ]
    return TypeTranslation(
        sort=sort,
        encode=enc,
        decode=dec,
        inner_kind="scalar",
        from_json=from_json,
    )


# ---------------------------------------------------------------------------
# Union / Optional handling
# ---------------------------------------------------------------------------


def _strip_optional(typ: TypeForm) -> tuple[TypeForm, bool]:
    """Peel a single ``T | None`` layer; return ``(inner, was_optional)``.

    The returned inner may itself be a union (``int | str``); the caller
    is responsible for classifying it via ``_classify_primitive_union``.
    """
    origin = get_origin(typ)
    if origin in {Union, UnionType}:
        non_none = [a for a in get_args(typ) if a is not NoneType]
        had_none = NoneType in get_args(typ)
        if had_none and len(non_none) == 1:
            return non_none[0], True
        if had_none and len(non_none) > 1:
            # rebuild the union without None via PEP 604 ``|``; the
            # ``X | Y`` operator is the only PEP-604-compliant way to
            # construct a ``UnionType`` from a runtime sequence. The
            # local lambda avoids ``operator.or_``'s partially-typed
            # typeshed stub.
            def _union(a: TypeForm, b: TypeForm) -> TypeForm:
                return cast("TypeForm", a | b)

            return reduce(_union, non_none), True
    return typ, False


# ---------------------------------------------------------------------------
# Union of primitive scalars
# ---------------------------------------------------------------------------


def _classify_primitive_union(args: tuple[TypeForm, ...]) -> TypeTranslation:
    """Classify a union whose every arm is a registered scalar.

    The encoded form is a JSON literal (``42``, ``"hello"``, ``1.5``); the
    decoder uses ``json.loads`` and dispatches on the resulting Python
    type. The synthesised sort name lists each arm's panproto sort in a
    canonical order so that equivalent unions produce the same sort.
    """
    arms: list[type] = []
    for arm in args:
        if not (isinstance(arm, type) and arm in _SCALARS):
            msg = (
                "didactic supports unions only when every arm is a registered "
                f"scalar; got arm {arm!r} in union {args!r}. Use a "
                "dx.TaggedUnion subclass for richer sums."
            )
            raise TypeNotSupportedError(msg)
        arms.append(arm)

    # canonical order: by sort name, deduplicated. Preserves runtime
    # behaviour while making ``int | str`` and ``str | int`` agree.
    arms_by_sort = {_SCALARS[a][0]: a for a in arms}
    sorted_sorts = sorted(arms_by_sort)
    sort = "Union " + " ".join(_paren(s) for s in sorted_sorts)

    def enc(v: FieldValue) -> Encoded:
        # bool is an int subclass; check it first so ``True`` doesn't
        # decode as ``1`` on the int arm.
        for arm in (bool, *(a for a in arms if a is not bool)):
            if arm in arms_by_sort.values() and isinstance(v, arm):
                return json.dumps(v if not isinstance(v, bytes) else v.hex())
        msg = f"value {v!r} did not match any arm of union {arms!r}"
        raise TypeError(msg)

    def dec(s: Encoded) -> FieldValue:
        loaded = json.loads(s)
        return _dispatch_union_arm(loaded, arms_by_sort)

    def from_json(value: JsonValue) -> FieldValue:
        return _dispatch_union_arm(value, arms_by_sort)

    return TypeTranslation(
        sort=sort,
        encode=enc,
        decode=dec,
        inner_kind="scalar",
        from_json=from_json,
    )


def _dispatch_union_arm(value: JsonValue, arms_by_sort: dict[str, type]) -> FieldValue:
    """Pick the union arm whose Python type matches ``value`` and decode."""
    arms = list(arms_by_sort.values())
    # bool first (subclass of int)
    if bool in arms and isinstance(value, bool):
        return value
    for arm in arms:
        if arm is bool:
            continue
        if isinstance(value, arm):
            # the matched scalar arm is a subset of FieldValue; the
            # union narrowing on ``value`` keeps it as JsonValue so we
            # cast at the boundary.
            return cast("FieldValue", value)
    msg = (
        f"value {value!r} (type {type(value).__name__}) did not match any "
        f"arm of union {arms!r}"
    )
    raise TypeError(msg)


# ---------------------------------------------------------------------------
# Annotated handling
# ---------------------------------------------------------------------------


def _expand_type_alias(typ: TypeForm) -> TypeForm:
    """Substitute concrete arguments through a PEP 695 type alias.

    Two shapes are recognised:

    1. ``Foo[X, Y]`` where ``Foo`` is a ``TypeAliasType`` such as
       ``type Foo[T, U] = Annotated[T, ..., U]``. Returns the alias's
       ``__value__`` with each ``TypeVar`` replaced by the matching
       argument. The didactic ``Embed`` and ``Ref`` aliases are the
       only in-tree producers of this shape.
    2. A bare ``TypeAliasType`` such as ``type Kind = Literal["a","b"]``.
       Returns the alias's ``__value__`` directly.

    Substitution walks one level of ``Annotated[...]`` and replaces type
    variables that appear either as the base type or anywhere in the
    metadata tuple. Other type-alias shapes are out of scope.
    """
    # bare alias: ``type Kind = Literal[...]``. ``TypeAliasType`` falls
    # outside the static ``TypeForm`` union (which only covers nominal
    # ``type`` and ``UnionType``), so the isinstance check needs an
    # ``object`` view of ``typ``.
    if isinstance(cast("object", typ), TypeAliasType):
        alias = cast("TypeAliasType", typ)
        return cast("TypeForm", alias.__value__)
    # parameterised alias: ``Foo[X, Y]``
    origin = get_origin(typ)
    if not isinstance(origin, TypeAliasType):
        return typ
    params = origin.__type_params__
    args = get_args(typ)
    if len(params) != len(args):
        return typ
    substitution: dict[Opaque, Opaque] = dict(zip(params, args, strict=True))
    value = origin.__value__
    if get_origin(value) is Annotated:
        value_args = get_args(value)
        new_base = substitution.get(value_args[0], value_args[0])
        new_meta = tuple(substitution.get(m, m) for m in value_args[1:])
        return cast("TypeForm", Annotated[new_base, *new_meta])
    return cast("TypeForm", substitution.get(value, value))


def unwrap_annotated(typ: TypeForm) -> tuple[TypeForm, tuple[Opaque, ...]]:
    """Split ``Annotated[T, x, y, z]`` into ``(T, (x, y, z))``.

    Parameters
    ----------
    typ
        The (possibly Annotated-wrapped) type. PEP 695 type aliases
        whose value is ``Annotated[...]`` are expanded first so callers
        can treat them uniformly.

    Returns
    -------
    tuple
        ``(base_type, metadata)``. If ``typ`` was not Annotated, metadata
        is an empty tuple and ``base_type`` is ``typ``.
    """
    expanded = _expand_type_alias(typ)
    if get_origin(expanded) is Annotated:
        args = get_args(expanded)
        return args[0], tuple(args[1:])
    return expanded, ()


# ---------------------------------------------------------------------------
# Container handling
# ---------------------------------------------------------------------------


def _classify_tuple(
    args: tuple[TypeForm | EllipsisType, ...],
) -> TypeTranslation:
    # tuple[T, ...] -> List T
    if len(args) == 2 and args[1] is Ellipsis:
        head = args[0]
        assert not isinstance(head, EllipsisType)
        inner = classify(head)

        def from_json(value: JsonValue) -> FieldValue:
            if not isinstance(value, list):
                msg = f"expected JSON list, got {type(value).__name__}"
                raise TypeError(msg)
            return tuple(inner.from_json(item) for item in value)

        return TypeTranslation(
            sort=f"List {_paren(inner.sort)}",
            encode=_make_list_encoder(inner.encode),
            decode=_make_list_decoder(inner.decode),
            inner_kind="list",
            from_json=from_json,
        )
    # heterogeneous tuple; defer until we have product-sort support
    msg = (
        "Heterogeneous tuples (e.g. tuple[A, B, C]) are not yet supported; "
        "use a nested dx.Model or a tuple[T, ...] for now."
    )
    raise TypeNotSupportedError(msg)


def _make_list_encoder(
    inner_encode: Callable[[FieldValue], Encoded],
) -> Callable[[FieldValue], Encoded]:
    def enc(v: FieldValue) -> Encoded:
        # JSON-encode the encoded items; the panproto string is therefore
        # always a valid JSON array literal.
        assert isinstance(v, tuple)
        return json.dumps([inner_encode(item) for item in v])

    return enc


def _make_list_decoder(
    inner_decode: Callable[[Encoded], FieldValue],
) -> Callable[[Encoded], tuple[FieldValue, ...]]:
    def dec(s: Encoded) -> tuple[FieldValue, ...]:
        items: JsonValue = json.loads(s)
        if not isinstance(items, list):
            msg = f"expected JSON list, got {type(items).__name__}"
            raise TypeError(msg)
        return tuple(inner_decode(x) for x in cast("list[Encoded]", items))

    return dec


def _classify_frozenset(args: tuple[TypeForm, ...]) -> TypeTranslation:
    if len(args) != 1:
        msg = f"frozenset must have exactly one type parameter; got {args!r}"
        raise TypeNotSupportedError(msg)
    inner = classify(args[0])

    def enc(v: FieldValue) -> Encoded:
        assert isinstance(v, frozenset)
        return json.dumps(sorted(inner.encode(item) for item in v))

    def dec(s: Encoded) -> frozenset[FieldValue]:
        items: JsonValue = json.loads(s)
        if not isinstance(items, list):
            msg = f"expected JSON list for frozenset, got {type(items).__name__}"
            raise TypeError(msg)
        return frozenset(inner.decode(x) for x in cast("list[Encoded]", items))

    def from_json(value: JsonValue) -> FieldValue:
        if not isinstance(value, list):
            msg = f"expected JSON list for frozenset, got {type(value).__name__}"
            raise TypeError(msg)
        return frozenset(inner.from_json(item) for item in value)

    return TypeTranslation(
        sort=f"Set {_paren(inner.sort)}",
        encode=enc,
        decode=dec,
        inner_kind="set",
        from_json=from_json,
    )


def _classify_dict(args: tuple[TypeForm, ...]) -> TypeTranslation:
    if len(args) != 2:
        msg = f"dict must have exactly two type parameters; got {args!r}"
        raise TypeNotSupportedError(msg)
    key_type, value_type = args
    if key_type is not str:
        msg = (
            "didactic dict fields must use str keys; "
            f"got dict[{key_type!r}, ...]. Use a nested dx.Model for keyed records."
        )
        raise TypeNotSupportedError(msg)
    inner = classify(value_type)

    def enc(v: FieldValue) -> Encoded:
        assert isinstance(v, dict)
        return json.dumps({k: inner.encode(val) for k, val in v.items()})

    def dec(s: Encoded) -> dict[str, FieldValue]:
        items: JsonValue = json.loads(s)
        if not isinstance(items, dict):
            msg = f"expected JSON object for dict, got {type(items).__name__}"
            raise TypeError(msg)
        return {
            k: inner.decode(v) for k, v in cast("dict[str, Encoded]", items).items()
        }

    def from_json(value: JsonValue) -> FieldValue:
        if not isinstance(value, dict):
            msg = f"expected JSON object for dict, got {type(value).__name__}"
            raise TypeError(msg)
        return {k: inner.from_json(v) for k, v in value.items()}

    return TypeTranslation(
        sort=f"Map String {_paren(inner.sort)}",
        encode=enc,
        decode=dec,
        inner_kind="map",
        from_json=from_json,
    )


# ---------------------------------------------------------------------------
# Literal (enum) handling
# ---------------------------------------------------------------------------


def _classify_literal(args: tuple[FieldValue, ...]) -> TypeTranslation:
    if not args:
        msg = "Literal[...] must have at least one value"
        raise TypeNotSupportedError(msg)
    # require all args to share a single concrete type
    types = {type(a) for a in args}
    if len(types) != 1:
        msg = (
            f"Literal members must all share one type; got {types!r}. "
            "Use a discriminated dx.TaggedUnion for heterogeneous enums."
        )
        raise TypeNotSupportedError(msg)
    inner_type = next(iter(types))
    if inner_type not in _SCALARS:
        msg = f"Literal of {inner_type.__name__} is not a supported sort"
        raise TypeNotSupportedError(msg)
    inner = _scalar_translation(inner_type)
    members = ", ".join(repr(a) for a in args)

    allowed: frozenset[FieldValue] = frozenset(args)

    def enc(v: FieldValue) -> Encoded:
        if v not in allowed:
            msg = f"value {v!r} is not in Literal[{members}]"
            raise ValueError(msg)
        return inner.encode(v)

    def dec(s: Encoded) -> FieldValue:
        v = inner.decode(s)
        if v not in allowed:
            msg = f"decoded value {v!r} is not in Literal[{members}]"
            raise ValueError(msg)
        return v

    def from_json(v: JsonValue) -> FieldValue:
        decoded = inner.from_json(v)
        if decoded not in allowed:
            msg = f"value {decoded!r} is not in Literal[{members}]"
            raise ValueError(msg)
        return decoded

    return TypeTranslation(
        sort=f"Enum {{{members}}}",
        encode=enc,
        decode=dec,
        inner_kind="enum",
        from_json=from_json,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def classify(typ: TypeForm) -> TypeTranslation:  # noqa: PLR0911
    """Classify a Python type hint and return a TypeTranslation.

    Parameters
    ----------
    typ
        The annotation to classify. Must be already resolved (no
        ForwardRef objects, no string annotations).

    Returns
    -------
    TypeTranslation
        The sort name, encoder, decoder, and classification metadata.

    Raises
    ------
    TypeNotSupportedError
        If the annotation is not (yet) representable as a panproto sort.

    See Also
    --------
    unwrap_annotated : split Annotated metadata before calling classify.
    """
    # Expand PEP 695 type aliases (``Embed[T]``, ``Ref[T]``) so the
    # downstream Annotated logic sees the underlying form.
    typ = _expand_type_alias(typ)
    # Annotated[T, ...]; strip metadata, recurse on the base
    if get_origin(typ) is Annotated:
        base, metadata = unwrap_annotated(typ)
        # ``Ref[Foo]`` injects a Ref sentinel; classify as a string-id edge
        if _has_ref_marker(metadata):
            return _ref_translation(metadata)
        # ``Embed[Foo]`` injects an Embed sentinel; classify as an owned sub-vertex
        if _has_embed_marker(metadata):
            return _embed_translation(base, metadata)
        inner = classify(base)
        # the rest of the metadata is consumed elsewhere (in _fields.FieldSpec)
        return TypeTranslation(
            sort=inner.sort,
            encode=inner.encode,
            decode=inner.decode,
            is_optional=inner.is_optional,
            inner_kind=(
                inner.inner_kind if inner.inner_kind != "scalar" else "refinement"
            ),
            from_json=inner.from_json,
        )

    # T | None; unwrap a single Optional layer
    inner_type, was_optional = _strip_optional(typ)
    if was_optional:
        inner = classify(inner_type)

        def enc(v: FieldValue) -> Encoded:
            return "null" if v is None else inner.encode(v)

        def dec(s: Encoded) -> FieldValue:
            return None if s == "null" else inner.decode(s)

        def from_json(v: JsonValue) -> FieldValue:
            return None if v is None else inner.from_json(v)

        return TypeTranslation(
            sort=f"Maybe {_paren(inner.sort)}",
            encode=enc,
            decode=dec,
            is_optional=True,
            inner_kind=inner.inner_kind,
            from_json=from_json,
        )

    # scalar
    if isinstance(inner_type, type) and _is_scalar(inner_type):
        return _scalar_translation(inner_type)

    # parameterised generics
    origin = get_origin(inner_type)
    args = get_args(inner_type)

    # union of primitive scalars (e.g. ``int | str``); raw unions of
    # non-primitives still raise via _classify_primitive_union below.
    if origin in {Union, UnionType}:
        return _classify_primitive_union(args)

    if origin is tuple:
        return _classify_tuple(args)
    if origin is frozenset:
        return _classify_frozenset(args)
    if origin is dict:
        return _classify_dict(args)
    if origin is Literal:
        return _classify_literal(args)

    # mutable containers; explicitly rejected
    is_mutable_origin = origin in {list, set}
    is_mutable_type = inner_type in {list, set, dict}
    if is_mutable_origin or is_mutable_type:
        msg = (
            f"Mutable container types ({origin or inner_type}) are not "
            "first-class didactic field types. Use tuple[T, ...], frozenset[T], "
            "or dict[str, V]."
        )
        raise TypeNotSupportedError(msg)

    msg = f"Type {typ!r} is not (yet) translatable to a panproto sort."
    raise TypeNotSupportedError(msg)


def _paren(sort: str) -> str:
    """Wrap a multi-word sort name in parentheses where needed."""
    return f"({sort})" if " " in sort else sort


# ---------------------------------------------------------------------------
# Ref / Embed handling
# ---------------------------------------------------------------------------


def _has_ref_marker(metadata: tuple[Opaque, ...]) -> bool:
    """Whether the metadata tuple includes the Ref sentinel.

    Imported lazily to avoid a cycle: ``_refs`` does not depend on ``_types``,
    but ``_types`` needs to know about the sentinel for classification.
    """
    from didactic.fields._refs import RefSentinel  # noqa: PLC0415

    return any(isinstance(m, RefSentinel) for m in metadata)


def _ref_translation(metadata: tuple[Opaque, ...]) -> TypeTranslation:
    """Build a TypeTranslation for a ``Ref[T]`` field.

    Stored as the target's primary id (a ``str``). The target's name is
    captured in the sort string so the theory builder can emit an edge.

    The Ref alias expands to ``Annotated[str, REF_MARKER, T]``; this
    function recovers ``T`` from the metadata as the first non-sentinel
    entry that names a class or forward-ref string.
    """
    from didactic.fields._refs import RefSentinel  # noqa: PLC0415

    target: Opaque = None
    for m in metadata:
        if isinstance(m, RefSentinel):
            continue
        if isinstance(m, (type, str)):
            target = m
            break
    if target is None:
        msg = "Ref[T] metadata is missing the target type slot"
        raise TypeNotSupportedError(msg)
    target_name: str
    if isinstance(target, type):
        target_name = target.__name__
    else:
        # narrowed to str by the search loop above
        assert isinstance(target, str)
        target_name = target

    def encode(v: FieldValue) -> Encoded:
        # accept either a string id or a Model with an `id` attribute
        if isinstance(v, str):
            return v
        target_id = getattr(v, "id", None)
        if isinstance(target_id, str):
            return target_id
        msg = (
            f"Ref[{target_name}] expected a string id or a Model with "
            f"`.id: str`; got {type(v).__name__}"
        )
        raise TypeError(msg)

    def _ref_decode(s: Encoded) -> FieldValue:
        return s

    def _ref_from_json(v: JsonValue) -> FieldValue:
        # a Ref's wire form is the target's id, always a string
        assert isinstance(v, str)
        return v

    return TypeTranslation(
        sort=f"Ref {target_name}",
        encode=encode,
        decode=_ref_decode,
        inner_kind="ref",
        from_json=_ref_from_json,
    )


def _has_embed_marker(metadata: tuple[Opaque, ...]) -> bool:
    """Whether the metadata tuple includes the Embed sentinel."""
    from didactic.fields._refs import EmbedSentinel  # noqa: PLC0415

    return any(isinstance(m, EmbedSentinel) for m in metadata)


def _embed_translation(base: TypeForm, metadata: tuple[Opaque, ...]) -> TypeTranslation:
    """Build a TypeTranslation for an ``Embed[T]`` field.

    Stored as the JSON-encoded storage dict of the embedded Model. Decoded
    by reconstructing a ``T`` via its private ``from_storage_dict`` hook
    (no validation re-runs because the storage is already in encoded form).

    Parameters
    ----------
    base
        The expanded base type of the surrounding ``Annotated[T, ...]``
        form; ``T`` itself, recovered from the alias substitution.
    metadata
        The annotation's metadata tuple; only used to assert that the
        Embed sentinel is present (the target is read from ``base``).

    Notes
    -----
    The target ``T`` must be a [didactic.api.Model][didactic.api.Model] subclass.
    String forward references are not supported here yet; Embed targets
    must be resolved by classification time.
    """
    from didactic.fields._refs import EmbedSentinel  # noqa: PLC0415
    from didactic.models._model import Model  # noqa: PLC0415

    assert any(isinstance(m, EmbedSentinel) for m in metadata)
    if not (isinstance(base, type) and issubclass(base, Model)):
        msg = (
            f"Embed[T] target must be a didactic.Model subclass; got {base!r}. "
            "String forward references are not yet supported for Embed."
        )
        raise TypeNotSupportedError(msg)

    target_cls: type[Model] = base
    target_name = target_cls.__name__

    def encode(v: FieldValue) -> Encoded:
        # accept either a target_cls instance or a dict (which we route
        # through model_validate to produce one). This makes the
        # model_dump -> model_validate round-trip work transparently.
        if isinstance(v, target_cls):
            return json.dumps(v.to_storage_dict())
        if isinstance(v, dict):
            return json.dumps(target_cls.model_validate(v).to_storage_dict())
        msg = (
            f"Embed[{target_name}] expected a {target_name} instance or dict; "
            f"got {type(v).__name__}"
        )
        raise TypeError(msg)

    def decode(s: Encoded) -> FieldValue:
        items = json.loads(s)
        if not isinstance(items, dict):
            msg = (
                f"expected JSON object for Embed[{target_name}]; "
                f"got {type(items).__name__}"
            )
            raise TypeError(msg)
        return target_cls.from_storage_dict(items)

    def from_json(v: JsonValue) -> FieldValue:
        # the JSON form is the model_dump dict (decoded values), not the
        # storage dict; route through model_validate to re-encode.
        if isinstance(v, dict):
            return target_cls.model_validate(v)
        msg = f"expected JSON object for Embed[{target_name}]; got {type(v).__name__}"
        raise TypeError(msg)

    return TypeTranslation(
        sort=f"Embed {target_name}",
        encode=encode,
        decode=decode,
        inner_kind="embed",
        from_json=from_json,
    )


__all__ = [
    "TypeNotSupportedError",
    "TypeTranslation",
    "classify",
    "unwrap_annotated",
]
