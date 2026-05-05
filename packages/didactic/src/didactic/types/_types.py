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
from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from functools import reduce
from pathlib import PurePath
from types import EllipsisType, GenericAlias, NoneType, UnionType
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

    from didactic.models._model import Model
    from didactic.types._typing import Encoded, FieldValue, JsonValue, Opaque

# A theory-spec record contributed by a translation: a sort declaration
# or an operation declaration. The shape mirrors ``build_theory_spec``'s
# spec dicts (sorts/ops are JSON-serialisable maps).
type SpecRecord = dict[str, "JsonValue"]

# The widest annotation form ``classify`` accepts. Includes the nominal
# ``type`` (covering bare classes and pyright's special-cased parameterised
# generics like ``tuple[int, ...]`` and ``dict[str, int]``), PEP 604
# ``UnionType`` (``int | None``), which pyright does *not* narrow to
# ``type``, and PEP 695 ``TypeAliasType`` instances. ``typing.Annotated``
# values and ``typing.Union[...]`` are also accepted at runtime; callers
# that pass them rely on pyright's legacy structural acceptance of those
# forms or use ``cast`` at the boundary.
TypeForm = type | UnionType | TypeAliasType | GenericAlias

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

    auxiliary_sorts: tuple[SpecRecord, ...] = ()
    """Extra sort declarations the parent Model's Theory must include.

    Populated by translations that generate auxiliary panproto sorts
    beyond the field's primary sort: currently only the Model-ref
    recursive-alias translation, which contributes a closed sum sort
    plus optional ``List`` / ``Map`` helper sorts. Empty for every
    other translation. ``build_theory_spec`` walks this on each field
    spec and merges by sort name (later duplicates dropped).
    """

    auxiliary_ops: tuple[SpecRecord, ...] = ()
    """Extra operation declarations the parent Model's Theory must include.

    The constructor operations of any auxiliary sum / list / map sort
    declared in :attr:`auxiliary_sorts`. Walked alongside the sorts
    in ``build_theory_spec``; deduped by op name.
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
    if not isinstance(typ, type):
        return False
    cls = cast("type[object]", typ)
    if cls in _SCALARS:
        return True
    if issubclass(cls, PurePath):
        return True
    return _enum_kind(cls) is not None


def _scalar_translation(typ: type) -> TypeTranslation:
    cls = cast("type[object]", typ)
    if cls in _SCALARS:
        sort, enc, dec, from_json = _SCALARS[cls]
        return TypeTranslation(
            sort=sort,
            encode=enc,
            decode=dec,
            inner_kind="scalar",
            from_json=from_json,
        )
    if issubclass(cls, PurePath):
        return _path_translation(cls)
    enum_kind = _enum_kind(cls)
    if enum_kind is not None:
        return _enum_translation(cls, enum_kind)
    msg = f"Type {cls!r} is not a registered scalar."
    raise TypeNotSupportedError(msg)


def _path_translation(typ: type) -> TypeTranslation:
    """Translate ``pathlib.Path`` (and any ``PurePath`` subclass).

    Wire format is ``str(path)``; decoding restores the same subclass.
    """

    def enc(v: FieldValue) -> Encoded:
        if not isinstance(v, PurePath):
            msg = f"expected PurePath for Path field, got {type(v).__name__}"
            raise TypeError(msg)
        return str(v)

    def dec(s: Encoded) -> FieldValue:
        return cast("FieldValue", typ(s))

    def from_json(v: JsonValue) -> FieldValue:
        if not isinstance(v, str):
            msg = f"expected JSON string for Path field, got {type(v).__name__}"
            raise TypeError(msg)
        return cast("FieldValue", typ(v))

    return TypeTranslation(
        sort="Path",
        encode=enc,
        decode=dec,
        inner_kind="scalar",
        from_json=from_json,
    )


def _enum_kind(typ: type) -> Literal["str", "int"] | None:
    """Classify an Enum subclass as string- or integer-valued.

    Returns ``"str"`` for ``StrEnum`` (or any ``Enum`` whose member
    values are all ``str``), ``"int"`` for ``IntEnum`` (or any
    ``Enum`` whose member values are all ``int``), and ``None``
    otherwise (the enum is rejected at classify time, with a message
    that points to the supported shapes).
    """
    if not issubclass(typ, enum.Enum):
        return None
    if issubclass(typ, enum.StrEnum):
        return "str"
    if issubclass(typ, enum.IntEnum):
        return "int"
    members = list(typ)
    if not members:
        return None
    if all(isinstance(m.value, bool) for m in members):
        # ``bool`` is a subclass of ``int``; reject so the user
        # isn't surprised by True/False round-tripping as 1/0.
        return None
    if all(isinstance(m.value, str) for m in members):
        return "str"
    if all(isinstance(m.value, int) for m in members):
        return "int"
    return None


def _enum_translation(typ: type, kind: Literal["str", "int"]) -> TypeTranslation:
    """Translate an ``enum.Enum`` subclass as ``String`` or ``Int``.

    The wire format is the member's ``value`` (a ``str`` for
    ``StrEnum`` / string-valued enums, an ``int`` for ``IntEnum`` /
    int-valued enums). Decode reconstructs the member via
    ``EnumCls(value)``, raising ``ValueError`` if the value isn't a
    registered member.
    """
    sort = "String" if kind == "str" else "Int"
    enum_cls = cast("type[enum.Enum]", typ)

    def enc(v: FieldValue) -> Encoded:
        # Accept either an enum member or its raw value (matches
        # Pydantic; lets ``model_validate({"color": "red"})`` work
        # without the caller having to wrap in ``EnumCls(...)`` first).
        member: enum.Enum
        if isinstance(v, enum_cls):
            member = v
        else:
            try:
                member = enum_cls(v)
            except (ValueError, TypeError) as exc:
                msg = f"value {v!r} is not a member or value of {enum_cls.__name__}"
                raise TypeError(msg) from exc
        if kind == "str":
            return json.dumps(member.value)
        return json.dumps(int(member.value))

    def dec(s: Encoded) -> FieldValue:
        raw = json.loads(s)
        return cast("FieldValue", enum_cls(raw))

    def from_json(v: JsonValue) -> FieldValue:
        if kind == "str":
            if not isinstance(v, str):
                msg = (
                    f"expected JSON string for {enum_cls.__name__}, "
                    f"got {type(v).__name__}"
                )
                raise TypeError(msg)
        elif not isinstance(v, int) or isinstance(v, bool):
            msg = (
                f"expected JSON integer for {enum_cls.__name__}, got {type(v).__name__}"
            )
            raise TypeError(msg)
        return cast("FieldValue", enum_cls(v))

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
# Recursive JSON-shaped type aliases
# ---------------------------------------------------------------------------

# A "JSON-shaped" recursive type alias is one whose ``__value__`` is built
# entirely from primitive scalars (str/int/float/bool/None), the
# JSON-compatible containers ``list[X]``/``tuple[X, ...]``/``dict[str, X]``,
# unions of these, and self-references (which appear as bare strings inside
# the alias body, e.g. ``list["JsonValue"]``). The motivating shape is::
#
#     type JsonValue = (
#         str | int | float | bool | None
#         | list["JsonValue"] | tuple["JsonValue", ...]
#         | dict[str, "JsonValue"]
#     )
#
# Such aliases are treated as opaque values of a single panproto sort
# named after the alias (``"JsonValue"`` in the example above). The
# encoded form is a JSON literal; the decoder is ``json.loads`` plus a
# recursive ``list -> tuple`` coercion so the result satisfies didactic's
# tuple-based ``FieldValue`` type. Recursive aliases that are NOT
# JSON-shaped (e.g. one that admits ``bytes`` or a non-Model class) are
# rejected with a clear error rather than silently accepted.

_JSON_PRIMITIVE_TYPES: frozenset[type] = frozenset({str, int, float, bool, NoneType})


def _arm_is_json_shape(arm: object, alias_name: str, alias_id: int, depth: int) -> bool:
    """Return True iff ``arm`` is a JSON-shaped type expression.

    Uses ``alias_name`` to recognise self-reference forward strings, and
    ``alias_id`` to recognise self-reference via ``TypeAliasType``
    identity. ``depth`` bounds recursion to guard against pathological
    nesting (e.g. mutual recursion not yet supported).
    """
    if depth > 64:
        return False
    if isinstance(arm, type) and arm in _JSON_PRIMITIVE_TYPES:
        return True
    if isinstance(arm, str) and arm == alias_name:
        return True
    if isinstance(arm, TypeAliasType) and id(arm) == alias_id:
        return True
    origin = get_origin(arm)
    args = get_args(arm)
    if origin is list:
        return len(args) == 1 and _arm_is_json_shape(
            args[0], alias_name, alias_id, depth + 1
        )
    if origin is tuple:
        return (
            len(args) == 2
            and args[1] is Ellipsis
            and _arm_is_json_shape(args[0], alias_name, alias_id, depth + 1)
        )
    if origin is dict:
        return (
            len(args) == 2
            and args[0] is str
            and _arm_is_json_shape(args[1], alias_name, alias_id, depth + 1)
        )
    if origin in {Union, UnionType}:
        return all(_arm_is_json_shape(a, alias_name, alias_id, depth + 1) for a in args)
    return False


def _has_self_reference(typ: object, alias_name: str, alias_id: int) -> bool:
    """Return True iff ``typ``'s structure references the alias by name or identity."""
    if isinstance(typ, str) and typ == alias_name:
        return True
    if isinstance(typ, TypeAliasType) and id(typ) == alias_id:
        return True
    args = get_args(typ)
    return any(
        a is not Ellipsis and _has_self_reference(a, alias_name, alias_id) for a in args
    )


def _coerce_lists_to_tuples(v: JsonValue) -> FieldValue:
    """Walk a JSON-decoded value, converting every ``list`` to ``tuple``.

    didactic's ``FieldValue`` is a tuple-based recursive type (no mutable
    ``list``); JSON-decode produces lists. This coercion bridges the two
    so that values flowing out of the JSON-shaped translation satisfy
    ``FieldValue`` immutability.
    """
    if isinstance(v, list):
        return tuple(_coerce_lists_to_tuples(item) for item in v)
    if isinstance(v, dict):
        return {k: _coerce_lists_to_tuples(val) for k, val in v.items()}
    # primitives pass through; bool/int/float/str/None are FieldValue leaves.
    return cast("FieldValue", v)


def _json_alias_translation(alias_name: str) -> TypeTranslation:
    """Build a TypeTranslation for a JSON-shaped recursive alias.

    The encoded form is ``json.dumps(value)`` (which natively converts
    tuples to JSON arrays). Decoding parses the JSON and coerces any
    decoded lists to tuples. ``from_json`` performs the same coercion
    on values that have already been JSON-decoded by an outer layer.
    """

    def enc(v: FieldValue) -> Encoded:
        # ``json.dumps`` raises ``TypeError`` for non-JSON-shaped values
        # (bytes, Decimal, Model instances, etc.). That's the right
        # behaviour: the alias declared the value space.
        return json.dumps(v)

    def dec(s: Encoded) -> FieldValue:
        return _coerce_lists_to_tuples(json.loads(s))

    def from_json(v: JsonValue) -> FieldValue:
        return _coerce_lists_to_tuples(v)

    return TypeTranslation(
        sort=alias_name,
        encode=enc,
        decode=dec,
        inner_kind="scalar",
        from_json=from_json,
    )


# ---------------------------------------------------------------------------
# Model-ref recursive type aliases (closed sum sort)
# ---------------------------------------------------------------------------

# A "Model-ref recursive alias" is a recursive type alias whose arms
# include at least one ``dx.Model`` subclass alongside the JSON-shape
# allow-list (primitive scalars, list/tuple/dict containers,
# self-references). The motivating shape is::
#
#     class Heading(dx.Model):
#         text: str
#
#     type Component = (
#         str | int | Heading
#         | list["Component"] | dict[str, "Component"]
#     )
#
# These translate to a panproto-native closed sum sort. The metaclass
# emits a ``Structural`` sort named after the alias whose
# ``SortClosure`` is ``Closed`` against one ``Operation`` per arm:
#
#     Component_str(v: Component_str_value) -> Component
#     Component_int(v: Component_int_value) -> Component
#     Component_heading(v: Heading) -> Component
#     Component_list(v: Component_List) -> Component
#     Component_dict(v: Component_Map) -> Component
#
# ``Term::Case`` over the resulting sort is exhaustiveness-checked by
# panproto-gat. Wire format is a single-key JSON object whose key is
# the constructor name (matches the panproto term-of-closed-sort
# encoding); see :func:`_alias_sum_translation` for the encoder.

# Container payload sorts are Val-kinded with ``Str`` payloads in this
# release (Phase A of the plan). Phase B promotes them to parametric
# structural sorts shared with non-alias list/dict fields.

_PRIMITIVE_TAGS: dict[type, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    type(None): "none",
}


@dataclass(frozen=True, slots=True)
class _AliasSignature:
    """Structured summary of a Model-ref recursive alias's arm set."""

    model_arms: tuple[type, ...]
    primitives: frozenset[type]
    has_list: bool
    has_tuple: bool
    has_dict: bool


def _arm_is_model_or_json_shape(
    arm: object,
    alias_name: str,
    alias_id: int,
    depth: int,
    model_arms_out: list[type],
) -> bool:
    """Predicate for the wider Model-ref allow-list.

    Same as :func:`_arm_is_json_shape` but also admits ``dx.Model``
    subclasses; each Model class encountered is appended (deduped by
    identity) to ``model_arms_out`` so the caller can build the
    constructor-name table without a second walk.
    """
    if depth > 64:
        return False
    if isinstance(arm, type):
        if arm in _JSON_PRIMITIVE_TYPES:
            return True
        if _is_model_class(arm):
            if arm not in model_arms_out:
                model_arms_out.append(arm)
            return True
    if isinstance(arm, str) and arm == alias_name:
        return True
    if isinstance(arm, TypeAliasType) and id(arm) == alias_id:
        return True
    origin = get_origin(arm)
    args = get_args(arm)
    if origin is list:
        return len(args) == 1 and _arm_is_model_or_json_shape(
            args[0], alias_name, alias_id, depth + 1, model_arms_out
        )
    if origin is tuple:
        return (
            len(args) == 2
            and args[1] is Ellipsis
            and _arm_is_model_or_json_shape(
                args[0], alias_name, alias_id, depth + 1, model_arms_out
            )
        )
    if origin is dict:
        return (
            len(args) == 2
            and args[0] is str
            and _arm_is_model_or_json_shape(
                args[1], alias_name, alias_id, depth + 1, model_arms_out
            )
        )
    if origin in {Union, UnionType}:
        return all(
            _arm_is_model_or_json_shape(
                a, alias_name, alias_id, depth + 1, model_arms_out
            )
            for a in args
        )
    return False


def _is_model_class(cls: type) -> bool:
    """Return True iff ``cls`` is a ``dx.Model`` subclass.

    Imports ``Model`` lazily to avoid an import cycle (``models._model``
    indirectly imports the types module).
    """
    from didactic.models._model import Model  # noqa: PLC0415

    return issubclass(cls, Model)


def _collect_alias_signature(alias: TypeAliasType) -> _AliasSignature:
    """Walk a recursive Model-ref alias, return its arm signature.

    Assumes the alias has already passed
    :func:`_arm_is_model_or_json_shape`; the returned signature is
    well-formed.
    """
    model_arms: list[type] = []
    primitives: set[type] = set()
    flags = {"list": False, "tuple": False, "dict": False}
    aname = alias.__name__
    aid = id(alias)

    def walk(arm: object, depth: int) -> None:
        if depth > 64:
            return
        if isinstance(arm, type):
            if arm in _JSON_PRIMITIVE_TYPES:
                primitives.add(arm)
                return
            if _is_model_class(arm):
                if arm not in model_arms:
                    model_arms.append(arm)
                return
        if isinstance(arm, str) and arm == aname:
            return
        if isinstance(arm, TypeAliasType) and id(arm) == aid:
            return
        origin = get_origin(arm)
        args = get_args(arm)
        if origin is list:
            flags["list"] = True
            walk(args[0], depth + 1)
            return
        if origin is tuple:
            flags["tuple"] = True
            walk(args[0], depth + 1)
            return
        if origin is dict:
            flags["dict"] = True
            walk(args[1], depth + 1)
            return
        if origin in {Union, UnionType}:
            for a in args:
                walk(a, depth + 1)

    walk(alias.__value__, 0)
    return _AliasSignature(
        model_arms=tuple(model_arms),
        primitives=frozenset(primitives),
        has_list=flags["list"],
        has_tuple=flags["tuple"],
        has_dict=flags["dict"],
    )


def _model_arm_tag(cls: type) -> str:
    """Build the constructor tag fragment for a Model arm.

    Lower-cases the class name and strips any leading underscores
    (which conventionally mark test-only or private classes and
    shouldn't bleed into the on-wire constructor name).
    """
    return cls.__name__.lstrip("_").lower()


def _alias_constructor_table(
    alias_name: str, sig: _AliasSignature
) -> dict[str, type | str]:
    """Map constructor tag (e.g. ``Component_int``) to its arm dispatch key.

    For primitive arms the value is the Python ``type`` (used for
    instance-checking on encode and value identity on decode). For
    Model arms it's the Model class. For container arms the value is
    a marker string (``"list"``, ``"tuple"``, ``"dict"``) so the
    encoder can branch.
    """
    table: dict[str, type | str] = {}
    for typ in sig.primitives:
        table[f"{alias_name}_{_PRIMITIVE_TAGS[typ]}"] = typ
    for cls in sig.model_arms:
        tag = f"{alias_name}_{_model_arm_tag(cls)}"
        if tag in table:
            msg = (
                f"alias {alias_name!r} has two Model arms whose lowercased "
                f"names collide on constructor tag {tag!r}; rename one of the "
                "Model classes or use a wrapper subclass."
            )
            raise TypeNotSupportedError(msg)
        table[tag] = cls
    if sig.has_list:
        table[f"{alias_name}_list"] = "list"
    if sig.has_tuple:
        table[f"{alias_name}_tuple"] = "tuple"
    if sig.has_dict:
        table[f"{alias_name}_dict"] = "dict"
    return table


def _alias_aux_spec(
    alias_name: str, table: dict[str, type | str], sig: _AliasSignature
) -> tuple[tuple[SpecRecord, ...], tuple[SpecRecord, ...]]:
    """Build the auxiliary sort/op records for the alias's Theory.

    Returns
    -------
    tuple
        ``(sorts, ops)`` lists of plain dicts shaped for
        :func:`build_theory_spec`'s consumption. Each constructor op
        targets the alias's primary sum sort; the sum sort itself
        carries a ``Closed`` closure listing every constructor name.
    """
    constructor_names: list[JsonValue] = list(table)
    sorts: list[SpecRecord] = [
        {
            "name": alias_name,
            "params": [],
            "kind": "Structural",
            "closure": {"Closed": constructor_names},
        }
    ]
    ops: list[SpecRecord] = []
    # primitive constructors take a Val-Str-kinded arg and produce the sum sort
    for typ in sig.primitives:
        tag = f"{alias_name}_{_PRIMITIVE_TAGS[typ]}"
        arg_sort = f"{alias_name}__{_PRIMITIVE_TAGS[typ]}_value"
        sorts.append(
            {
                "name": arg_sort,
                "params": [],
                "kind": {"Val": _value_kind_for_primitive(typ)},
                "closure": "Open",
            }
        )
        ops.append(
            {
                "name": tag,
                "inputs": [["v", arg_sort, "No"]],
                "output": alias_name,
            }
        )
    # Model constructors take the Model's primary sort directly.
    for cls in sig.model_arms:
        tag = f"{alias_name}_{_model_arm_tag(cls)}"
        ops.append(
            {
                "name": tag,
                "inputs": [["v", cls.__name__, "No"]],
                "output": alias_name,
            }
        )
    # Container constructors share a Val-Str helper sort per container shape.
    if sig.has_list or sig.has_tuple:
        helper = f"{alias_name}__list_value"
        sorts.append(
            {
                "name": helper,
                "params": [],
                "kind": {"Val": "Str"},
                "closure": "Open",
            }
        )
        if sig.has_list:
            ops.append(
                {
                    "name": f"{alias_name}_list",
                    "inputs": [["v", helper, "No"]],
                    "output": alias_name,
                }
            )
        if sig.has_tuple:
            ops.append(
                {
                    "name": f"{alias_name}_tuple",
                    "inputs": [["v", helper, "No"]],
                    "output": alias_name,
                }
            )
    if sig.has_dict:
        helper = f"{alias_name}__dict_value"
        sorts.append(
            {
                "name": helper,
                "params": [],
                "kind": {"Val": "Str"},
                "closure": "Open",
            }
        )
        ops.append(
            {
                "name": f"{alias_name}_dict",
                "inputs": [["v", helper, "No"]],
                "output": alias_name,
            }
        )
    return tuple(sorts), tuple(ops)


_PRIMITIVE_VALUE_KIND: dict[type, str] = {
    str: "Str",
    int: "Int",
    float: "Float",
    bool: "Bool",
    type(None): "Null",
}


def _value_kind_for_primitive(typ: type) -> str:
    """Map a primitive Python type to its panproto ``ValueKind`` variant."""
    return _PRIMITIVE_VALUE_KIND[typ]


def _alias_sum_translation(alias: TypeAliasType) -> TypeTranslation:
    """Build a TypeTranslation for a Model-ref recursive alias.

    Encoded form is a single-key JSON object whose key is the
    constructor name (e.g. ``"Component_heading"``) and whose value
    is the constructor's payload (a primitive, a Model dump-dict,
    or a JSON array / object of inner-encoded values for the
    container constructors). The translation also exposes
    :attr:`TypeTranslation.auxiliary_sorts` and ``auxiliary_ops``
    so :func:`build_theory_spec` can splice the alias's sum sort
    and constructor ops into the parent Model's Theory.
    """
    alias_name = alias.__name__
    sig = _collect_alias_signature(alias)
    table = _alias_constructor_table(alias_name, sig)
    aux_sorts, aux_ops = _alias_aux_spec(alias_name, table, sig)

    # tag-by-Python-type for the encoder; primitives take precedence
    # over Models (a Model that happens to subclass int would still
    # round-trip via the int constructor, by design).
    primitive_tag_by_type = {
        typ: f"{alias_name}_{_PRIMITIVE_TAGS[typ]}" for typ in sig.primitives
    }
    model_tag_by_class = {
        cls: f"{alias_name}_{_model_arm_tag(cls)}" for cls in sig.model_arms
    }

    def encode_one(value: object, seen: set[int]) -> JsonValue:
        if id(value) in seen:
            msg = (
                f"alias {alias_name!r} value graph contains a cycle through "
                f"object id={id(value)}; cycle support is out of scope for "
                "this release."
            )
            raise ValueError(msg)
        seen = seen | {id(value)}
        # bool is an int subclass; check it before int.
        if isinstance(value, bool) and bool in primitive_tag_by_type:
            return {primitive_tag_by_type[bool]: value}
        if value is None and type(None) in primitive_tag_by_type:
            return {primitive_tag_by_type[type(None)]: None}
        if isinstance(value, str) and str in primitive_tag_by_type:
            return {primitive_tag_by_type[str]: value}
        if isinstance(value, int) and int in primitive_tag_by_type:
            return {primitive_tag_by_type[int]: value}
        if isinstance(value, float) and float in primitive_tag_by_type:
            return {primitive_tag_by_type[float]: value}
        for cls, tag in model_tag_by_class.items():
            if isinstance(value, cls):
                # Route through ``model_dump_json`` so any nested
                # ``tuple[Embed[T], ...]`` / ``dict[str, Embed[T]]`` /
                # nested-Model structures inside the variant get the
                # JSON-safe walk that ``model_dump`` alone skips.
                model_value = cast("Model", value)
                return cast(
                    "JsonValue", {tag: json.loads(model_value.model_dump_json())}
                )
        # Sequence values: prefer the ``tuple`` constructor when the
        # alias declares one, even for Python ``list`` input. This
        # keeps storage canonical (round-tripping a Python list and
        # re-encoding produces the same constructor name as if it had
        # been a tuple to begin with), matching the tuple-based
        # ``FieldValue`` invariant.
        if isinstance(value, (tuple, list)) and sig.has_tuple:
            seq = cast("tuple[FieldValue, ...] | list[FieldValue]", value)
            inner: list[JsonValue] = [encode_one(item, seen) for item in seq]
            return {f"{alias_name}_tuple": inner}
        if isinstance(value, list) and sig.has_list:
            lst = cast("list[FieldValue]", value)
            inner = [encode_one(item, seen) for item in lst]
            return {f"{alias_name}_list": inner}
        if isinstance(value, tuple) and sig.has_list:
            # Alias declares only ``list[X]`` but the user constructed
            # with a tuple: route through the list constructor so the
            # alias's declared constructor space is honoured.
            tup_for_list = cast("tuple[FieldValue, ...]", value)
            inner = [encode_one(item, seen) for item in tup_for_list]
            return {f"{alias_name}_list": inner}
        if isinstance(value, dict) and sig.has_dict:
            mapping = cast("dict[str, FieldValue]", value)
            inner_obj: dict[str, JsonValue] = {
                k: encode_one(v, seen) for k, v in mapping.items()
            }
            return {f"{alias_name}_dict": inner_obj}
        msg = (
            f"value of type {type(cast('Opaque', value)).__name__} does not "
            f"match any arm of alias {alias_name!r}; expected one of "
            f"{sorted(table)}."
        )
        raise TypeError(msg)

    def decode_one(payload: JsonValue) -> FieldValue:
        if not isinstance(payload, dict):
            msg = (
                f"alias {alias_name!r} payload must be a single-key dict "
                f"tagged by constructor; got {type(payload).__name__}."
            )
            raise TypeError(msg)
        if len(payload) != 1:
            msg = (
                f"alias {alias_name!r} payload must have exactly one "
                f"constructor key; got keys {sorted(payload)!r}."
            )
            raise ValueError(msg)
        ((tag, body),) = payload.items()
        if tag not in table:
            msg = (
                f"alias {alias_name!r} payload uses unknown constructor "
                f"{tag!r}; expected one of {sorted(table)!r}."
            )
            raise KeyError(tag)
        target = table[tag]
        if isinstance(target, type):
            if target in _JSON_PRIMITIVE_TYPES:
                # primitive arm; payload is the literal value
                return cast("FieldValue", body)
            # Model arm; route through ``model_validate_json`` so the
            # variant's per-field ``from_json`` callables run (e.g.
            # list -> tuple coercion for nested ``tuple[T, ...]`` fields,
            # ISO-string -> datetime for nested datetime fields).
            model_cls = cast("type[Model]", target)
            return model_cls.model_validate_json(json.dumps(body))
        # container arm; body is a JSON list/dict of inner-encoded values
        if target in {"list", "tuple"}:
            if not isinstance(body, list):
                msg = (
                    f"alias {alias_name!r} container constructor {tag!r} "
                    f"payload must be a JSON array; got "
                    f"{type(body).__name__}."
                )
                raise TypeError(msg)
            return tuple(decode_one(item) for item in body)
        # target == "dict"
        if not isinstance(body, dict):
            msg = (
                f"alias {alias_name!r} dict constructor {tag!r} payload "
                f"must be a JSON object; got {type(body).__name__}."
            )
            raise TypeError(msg)
        return {k: decode_one(v) for k, v in body.items()}

    def enc(v: FieldValue) -> Encoded:
        return json.dumps(encode_one(v, set()))

    def dec(s: Encoded) -> FieldValue:
        return decode_one(json.loads(s))

    def from_json(v: JsonValue) -> FieldValue:
        return decode_one(v)

    return TypeTranslation(
        sort=alias_name,
        encode=enc,
        decode=dec,
        inner_kind="sum",
        from_json=from_json,
        auxiliary_sorts=aux_sorts,
        auxiliary_ops=aux_ops,
    )


# ---------------------------------------------------------------------------
# TaggedUnion as field type (closed sum sort dispatched by discriminator)
# ---------------------------------------------------------------------------

# A ``dx.TaggedUnion`` subclass declared with a ``discriminator=`` keyword is
# a sum over the variants registered against it (``cls.__variants__``). When
# a Model field is annotated with the union root, the field accepts any
# variant; on encode the variant is dumped to its record dict (which already
# carries the discriminator value), on decode the discriminator field
# selects which variant to instantiate. The wire format is therefore the
# variant's natural ``model_dump`` shape; no envelope and no synthesised
# constructor tag is needed because the discriminator IS the constructor
# tag, baked into every variant.
#
# The translation also exposes the closed sum sort plus per-variant
# constructor ops via ``auxiliary_sorts`` / ``auxiliary_ops``, so the
# parent Model's Theory carries the same panproto-native sum-sort shape
# as a Model-ref recursive alias would.


def _is_tagged_union_root(cls: type) -> bool:
    """Return True iff ``cls`` is a ``TaggedUnion`` subclass with variants set."""
    from didactic.fields._unions import TaggedUnion  # noqa: PLC0415

    if not issubclass(cls, TaggedUnion):
        return False
    if cls is TaggedUnion:
        return False
    return cls.__discriminator__ is not None and bool(cls.__variants__)


def _tagged_union_translation(cls: type) -> TypeTranslation:
    """Build a TypeTranslation for a ``dx.TaggedUnion`` root used as a field type.

    The encoded form is the JSON dump of the chosen variant (a dict
    that already carries the discriminator field). The decoder
    inspects the discriminator field, looks the variant up in
    ``cls.__variants__``, and instantiates it via ``model_validate``.
    """
    discriminator = cast("str", cls.__discriminator__)  # type: ignore[attr-defined]
    union_name = cls.__name__
    initial_variants = cast(
        "dict[object, type[Model]]",
        cls.__variants__,  # type: ignore[attr-defined]
    )
    # Snapshot at classify time only for the auxiliary Theory shape;
    # the runtime encode/decode path reads ``cls.__variants__`` live so
    # variants registered after this field's classify call (mutually
    # recursive AST shapes are the canonical case) participate fully.
    aux_sorts, aux_ops = _tagged_union_aux_spec(
        union_name, discriminator, dict(initial_variants)
    )

    def current_variants() -> dict[object, type[Model]]:
        live = cast(
            "dict[object, type[Model]]",
            cls.__variants__,  # type: ignore[attr-defined]
        )
        return dict(live)

    def encode_one(value: object) -> JsonValue:
        variants_by_value = current_variants()
        # A dict carrying the discriminator is treated as a payload that
        # would dispatch on ``Root.model_validate``; convert it to the
        # matching variant instance before the wire dump. Without this,
        # ``BinOp.model_validate_json`` would hand each nested
        # ``{"kind": "lit", ...}`` dict straight to this encoder.
        if isinstance(value, dict) and discriminator in value:
            payload = cast("dict[str, JsonValue]", value)
            disc_value = cast("object", payload[discriminator])
            variant_cls = variants_by_value.get(disc_value)
            if variant_cls is not None:
                instance = variant_cls.model_validate_json(json.dumps(payload))
                return cast("JsonValue", json.loads(instance.model_dump_json()))
        for variant_cls in variants_by_value.values():
            if isinstance(value, variant_cls):
                # Route through ``model_dump_json`` so any nested
                # ``tuple[Embed[T], ...]`` / ``dict[str, Embed[T]]`` /
                # nested-Model fields inside the variant get the
                # JSON-safe walk that ``model_dump`` alone skips.
                return cast("JsonValue", json.loads(value.model_dump_json()))
        variant_names = sorted(
            cast("type", v).__name__ for v in variants_by_value.values()
        )
        value_type_name = type(cast("object", value)).__name__
        msg = (
            f"value of type {value_type_name} is not a registered variant "
            f"of TaggedUnion {union_name!r}; expected one of {variant_names}."
        )
        raise TypeError(msg)

    def decode_one(payload: JsonValue) -> FieldValue:
        variants_by_value = current_variants()
        if not isinstance(payload, dict):
            msg = (
                f"TaggedUnion {union_name!r} payload must be a dict; got "
                f"{type(payload).__name__}."
            )
            raise TypeError(msg)
        if discriminator not in payload:
            msg = (
                f"TaggedUnion {union_name!r} payload is missing discriminator "
                f"field {discriminator!r}; got keys {sorted(payload)!r}."
            )
            raise KeyError(discriminator)
        disc_value = payload[discriminator]
        variant_cls = variants_by_value.get(disc_value)
        if variant_cls is None:
            known_values = [repr(v) for v in variants_by_value]
            msg = (
                f"TaggedUnion {union_name!r} has no variant registered for "
                f"{discriminator}={disc_value!r}; expected one of "
                f"{known_values}."
            )
            raise KeyError(disc_value)
        # Route through ``model_validate_json`` so the variant's per-field
        # ``from_json`` callables get a chance to coerce JSON-shaped values
        # (e.g. list -> tuple for ``tuple[float, ...]`` fields) before
        # construction. ``model_validate`` would feed the raw JSON shape
        # straight to the field encoders, which expect Python-native types.
        return variant_cls.model_validate_json(json.dumps(payload))

    def enc(v: FieldValue) -> Encoded:
        return json.dumps(encode_one(v))

    def dec(s: Encoded) -> FieldValue:
        return decode_one(json.loads(s))

    def from_json(v: JsonValue) -> FieldValue:
        return decode_one(v)

    return TypeTranslation(
        sort=union_name,
        encode=enc,
        decode=dec,
        inner_kind="sum",
        from_json=from_json,
        auxiliary_sorts=aux_sorts,
        auxiliary_ops=aux_ops,
    )


def _tagged_union_aux_spec(
    union_name: str,
    discriminator: str,
    variants_by_value: dict[object, type[Model]],
) -> tuple[tuple[SpecRecord, ...], tuple[SpecRecord, ...]]:
    """Build the auxiliary sort/op records for a TaggedUnion used as a field type.

    Constructor names are ``<UnionName>_<discriminator-value>`` (the
    discriminator value is the natural variant identifier and matches
    what the wire format already carries). Each constructor op takes
    the variant's primary sort as its single input and outputs the
    union sort. The closed sum sort declares ``Closed`` against every
    constructor name.
    """
    constructor_table: dict[str, type[Model]] = {}
    for disc_value, variant_cls in variants_by_value.items():
        tag = f"{union_name}_{disc_value!s}"
        constructor_table[tag] = variant_cls
    constructor_names: list[JsonValue] = list(constructor_table)
    sorts: list[SpecRecord] = [
        {
            "name": union_name,
            "params": [],
            "kind": "Structural",
            "closure": {"Closed": constructor_names},
        }
    ]
    ops: list[SpecRecord] = [
        {
            "name": tag,
            "inputs": [["v", variant_cls.__name__, "No"]],
            "output": union_name,
        }
        for tag, variant_cls in constructor_table.items()
    ]
    # Reference the discriminator name in a metadata field on the sum
    # sort so consumers can introspect the dispatch convention without
    # round-tripping the Python class. The panproto schema spec ignores
    # unknown keys; this is purely informational.
    sorts[0]["discriminator"] = discriminator
    return tuple(sorts), tuple(ops)


# ---------------------------------------------------------------------------
# Annotated handling
# ---------------------------------------------------------------------------


def _expand_type_alias(typ: TypeForm) -> TypeForm:
    """Substitute concrete arguments through a PEP 695 type alias.

    Three shapes are recognised:

    1. ``Foo[X, Y]`` where ``Foo`` is a ``TypeAliasType`` such as
       ``type Foo[T, U] = Annotated[T, ..., U]``. Returns the alias's
       ``__value__`` with each ``TypeVar`` replaced by the matching
       argument. The didactic ``Embed`` and ``Ref`` aliases are the
       only in-tree producers of this shape.
    2. A bare non-recursive ``TypeAliasType`` such as
       ``type Kind = Literal["a","b"]``. Returns the alias's
       ``__value__`` directly.
    3. A recursive JSON-shaped ``TypeAliasType`` such as the canonical
       ``JsonValue``. Returns the alias *unchanged* so that ``classify``
       can build a ``_json_alias_translation`` for it. (Unwrapping a
       recursive alias would loop on the self-reference.)

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
        # recursive alias: leave unwrapped so classify can build the
        # appropriate fixpoint translation. Two recursive shapes are
        # accepted: pure JSON-shaped (handled by ``_json_alias_translation``)
        # and the wider Model-ref shape (``_alias_sum_translation``).
        # Anything else is rejected up front with a clear message.
        if _has_self_reference(alias.__value__, alias.__name__, id(alias)):
            model_arms_probe: list[type] = []
            if not _arm_is_model_or_json_shape(
                alias.__value__,
                alias.__name__,
                id(alias),
                0,
                model_arms_probe,
            ):
                msg = (
                    f"recursive type alias {alias.__name__!r} contains an arm "
                    "that is not in the supported allow-list (primitive "
                    "scalars, dx.Model subclasses, list[X], tuple[X, ...], "
                    "dict[str, X], unions of these, and self-references). "
                    "Restrict the alias to the supported subset, or use a "
                    "dx.TaggedUnion."
                )
                raise TypeNotSupportedError(msg)
            return cast("TypeForm", alias)
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


# Public re-export under a non-underscored name, intended for tests and
# tooling that need to introspect a PEP 695 alias substitution. The
# underscored ``_expand_type_alias`` name is retained for backwards
# compatibility within this module.
expand_type_alias = _expand_type_alias


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
        # always a valid JSON array literal. Accept list as well as tuple
        # so call sites migrating from Pydantic (which transparently
        # coerces list to tuple for tuple-typed fields) do not have to
        # rewrite every ``indices=[0, 1, 2]`` literal. Reject anything
        # else with ``TypeError`` so the caller's ``ValidationError``
        # carries the field name instead of a bare ``AssertionError``.
        if not isinstance(v, (tuple, list)):
            msg = (
                f"expected tuple or list for tuple[T, ...] field, "
                f"got {type(v).__name__}"
            )
            raise TypeError(msg)
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
        # Accept any non-string iterable that can lawfully be coerced to
        # ``frozenset`` (set, frozenset, list, tuple). The same reasoning
        # as the tuple encoder applies: Pydantic coerces, callers
        # migrating across should not have to rewrite every literal, and
        # rejecting via ``TypeError`` keeps the failure inside
        # ``ValidationError``.
        if isinstance(v, (str, bytes, bytearray)) or not isinstance(
            v, (frozenset, set, list, tuple)
        ):
            msg = (
                f"expected frozenset, set, list, or tuple for frozenset[T] "
                f"field, got {type(v).__name__}"
            )
            raise TypeError(msg)
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


def classify(typ: TypeForm) -> TypeTranslation:
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
    # downstream Annotated logic sees the underlying form. Recursive
    # aliases come back unwrapped; we dispatch on shape (Model-ref
    # gets the closed sum-sort translation; pure JSON-shaped gets the
    # opaque JSON-fixpoint translation).
    typ = _expand_type_alias(typ)
    if isinstance(cast("object", typ), TypeAliasType):
        alias = cast("TypeAliasType", typ)
        # ``_expand_type_alias`` only returns a ``TypeAliasType`` when
        # the alias passed the wider Model-or-JSON allow-list. Now
        # decide which translation to build: any Model arm forces the
        # sum-sort path; pure JSON-shaped uses the opaque fixpoint.
        sig = _collect_alias_signature(alias)
        if sig.model_arms:
            return _alias_sum_translation(alias)
        return _json_alias_translation(alias.__name__)
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

    # TaggedUnion root used as a field type: dispatch via the variants'
    # discriminator field. The translation contributes a closed sum
    # sort plus per-variant constructor ops to the parent Model's Theory.
    if isinstance(inner_type, type) and _is_tagged_union_root(inner_type):
        return _tagged_union_translation(inner_type)

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
        # accept either a target_cls instance or a dict. The dict path
        # goes through ``model_validate_json`` (not ``model_validate``)
        # so each per-field ``from_json`` runs and JSON-shape values
        # like ``[1, 2, 3]`` for a ``tuple[int, ...]`` field get the
        # list-to-tuple coercion before the field encoder asserts.
        if isinstance(v, target_cls):
            return json.dumps(v.to_storage_dict())
        if isinstance(v, dict):
            return json.dumps(
                target_cls.model_validate_json(json.dumps(v)).to_storage_dict()
            )
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
        return target_cls.from_storage_dict(cast("dict[str, str]", items))

    def from_json(v: JsonValue) -> FieldValue:
        # the JSON form is the model_dump dict (decoded values), not
        # the storage dict; route through ``model_validate_json`` so
        # the inner Model's per-field ``from_json`` runs (e.g. JSON
        # list -> tuple for nested ``tuple[T, ...]`` fields).
        if isinstance(v, dict):
            return target_cls.model_validate_json(json.dumps(v))
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
