"""Unit tests for the type-translation foundation."""

# Tests pass ``Annotated[T, ...]`` forms to ``classify`` and
# ``unwrap_annotated``; the static ``TypeForm`` alias doesn't
# include ``Annotated`` (a typing special form, not a class), but
# the runtime accepts it. Tracked in panproto/didactic#1.
# pyright: reportArgumentType=false

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

import pytest
from annotated_types import Ge, Le, MaxLen, MinLen

from didactic.types._types import TypeNotSupportedError, classify, unwrap_annotated

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue


def test_typing_aliases_importable_at_runtime() -> None:
    """The PEP 695 type aliases in ``didactic.types._typing`` import cleanly.

    The aliases are TYPE_CHECKING-only at every call site; an explicit
    runtime import smoke-tests the module's evaluation.
    """
    from didactic.types import _typing as typing_module

    assert typing_module.JsonValue is not None
    assert typing_module.JsonObject is not None
    assert typing_module.FieldValue is not None
    assert typing_module.Encoded is not None
    assert typing_module.ClassTarget is not None
    assert typing_module.DefaultOrMissing is not None
    # ``Opaque`` is a runtime-checkable Protocol; everything matches it
    assert isinstance(object(), typing_module.Opaque)


# -- scalars ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("typ", "value", "expected_sort"),
    [
        (str, "hello", "String"),
        (int, 42, "Int"),
        (float, 3.14, "Float64"),
        (bool, True, "Bool"),
        (bytes, b"\x00\xff", "Bytes"),
        (Decimal, Decimal("1.50"), "Decimal"),
    ],
)
def test_scalar_round_trip(typ: type, value: FieldValue, expected_sort: str) -> None:
    t = classify(typ)
    assert t.sort == expected_sort
    encoded = t.encode(value)
    assert isinstance(encoded, str)
    decoded = t.decode(encoded)
    assert decoded == value


def test_uuid_round_trip() -> None:
    u = UUID("12345678-1234-5678-1234-567812345678")
    t = classify(UUID)
    assert t.sort == "Uuid"
    assert t.decode(t.encode(u)) == u


def test_datetime_round_trip() -> None:
    now = datetime(2026, 4, 30, 12, 34, 56)
    t = classify(datetime)
    assert t.sort == "DateTime"
    assert t.decode(t.encode(now)) == now


def test_date_round_trip() -> None:
    d = date(2026, 4, 30)
    t = classify(date)
    assert t.sort == "Date"
    assert t.decode(t.encode(d)) == d


# -- optional ---------------------------------------------------------------


def test_optional_str() -> None:
    t = classify(str | None)
    assert t.sort == "Maybe String"
    assert t.is_optional
    assert t.decode(t.encode("a")) == "a"
    assert t.decode(t.encode(None)) is None


def test_optional_int() -> None:
    t = classify(int | None)
    assert t.sort == "Maybe Int"
    assert t.decode(t.encode(7)) == 7
    assert t.decode(t.encode(None)) is None


# -- containers -------------------------------------------------------------


def test_tuple_homogeneous() -> None:
    t = classify(tuple[int, ...])
    assert t.sort == "List Int"
    assert t.decode(t.encode((1, 2, 3))) == (1, 2, 3)


def test_tuple_of_strings() -> None:
    t = classify(tuple[str, ...])
    assert t.sort == "List String"
    assert t.decode(t.encode(("a", "b"))) == ("a", "b")


def test_frozenset() -> None:
    t = classify(frozenset[int])
    assert t.sort == "Set Int"
    assert t.decode(t.encode(frozenset([3, 1, 2]))) == frozenset([1, 2, 3])


def test_dict_of_str_to_int() -> None:
    t = classify(dict[str, int])
    assert t.sort == "Map String Int"
    assert t.decode(t.encode({"a": 1, "b": 2})) == {"a": 1, "b": 2}


def test_heterogeneous_tuple_rejected() -> None:
    with pytest.raises(TypeNotSupportedError):
        classify(tuple[int, str])


def test_dict_with_non_str_key_rejected() -> None:
    with pytest.raises(TypeNotSupportedError):
        classify(dict[int, str])


def test_mutable_list_rejected() -> None:
    with pytest.raises(TypeNotSupportedError):
        classify(list[int])


def test_mutable_set_rejected() -> None:
    with pytest.raises(TypeNotSupportedError):
        classify(set[int])


# -- literals ---------------------------------------------------------------


def test_string_literal() -> None:
    t = classify(Literal["red", "green", "blue"])
    assert "Enum" in t.sort
    assert t.decode(t.encode("red")) == "red"
    with pytest.raises(ValueError, match="not in Literal"):
        t.encode("yellow")


def test_mixed_literal_rejected() -> None:
    with pytest.raises(TypeNotSupportedError):
        classify(Literal["a", 1])


# -- annotated --------------------------------------------------------------


def test_annotated_int() -> None:
    t = classify(Annotated[int, Ge(0), Le(127)])
    assert t.sort == "Int"
    assert t.decode(t.encode(50)) == 50


def test_annotated_str_with_length_bounds() -> None:
    t = classify(Annotated[str, MinLen(1), MaxLen(10)])
    assert t.sort == "String"
    assert t.decode(t.encode("hello")) == "hello"


def test_unwrap_annotated() -> None:
    base, meta = unwrap_annotated(Annotated[int, Ge(0)])
    assert base is int
    assert len(meta) == 1


def test_unwrap_plain_type() -> None:
    base, meta = unwrap_annotated(int)
    assert base is int
    assert meta == ()


# -- nested -----------------------------------------------------------------


def test_nested_optional_tuple() -> None:
    t = classify(tuple[int, ...] | None)
    assert t.sort == "Maybe (List Int)"
    assert t.decode(t.encode((1, 2, 3))) == (1, 2, 3)
    assert t.decode(t.encode(None)) is None


def test_nested_dict_of_optional() -> None:
    t = classify(dict[str, int | None])
    assert t.sort == "Map String (Maybe Int)"
    src: dict[str, FieldValue] = {"a": 1, "b": None}
    decoded = t.decode(t.encode(src))
    assert decoded == src


# -- PEP 695 type aliases (gh #2.1) ----------------------------------------

type _AliasedKind = Literal["a", "b", "c"]
type _AliasedInt = int


def test_pep695_alias_to_literal_translates() -> None:
    t = classify(_AliasedKind)
    assert t.sort.startswith("Enum")
    assert t.decode(t.encode("a")) == "a"


def test_pep695_alias_to_scalar_translates() -> None:
    t = classify(_AliasedInt)
    assert t.sort == "Int"
    assert t.decode(t.encode(7)) == 7


def test_pep695_alias_inside_dict_translates() -> None:
    t = classify(dict[str, _AliasedKind])
    assert t.sort.startswith("Map String (Enum")
    src: dict[str, FieldValue] = {"x": "a", "y": "b"}
    assert t.decode(t.encode(src)) == src


# -- union of primitives (gh #3, #2.3) -------------------------------------


def test_union_int_str_translates() -> None:
    t = classify(int | str)
    assert "Int" in t.sort and "String" in t.sort
    assert t.decode(t.encode(42)) == 42
    assert t.decode(t.encode("hello")) == "hello"


def test_union_float_str_round_trip() -> None:
    t = classify(float | str)
    assert t.decode(t.encode(1.5)) == 1.5
    assert t.decode(t.encode("verse_2")) == "verse_2"


def test_union_with_none_then_two_primitives() -> None:
    t = classify(int | str | None)
    assert t.is_optional
    assert t.decode(t.encode(None)) is None
    assert t.decode(t.encode(7)) == 7
    assert t.decode(t.encode("x")) == "x"


def test_dict_value_union_of_primitives() -> None:
    t = classify(dict[str, int | float | str])
    src: dict[str, FieldValue] = {"a": 1, "b": 2.5, "c": "tag"}
    decoded = t.decode(t.encode(src))
    assert decoded == src


def test_union_of_non_primitives_still_rejected() -> None:
    class _M:
        pass

    with pytest.raises(TypeNotSupportedError):
        classify(int | _M)


# -- recursive JSON-shaped type aliases (gh #2.2) --------------------------

type _JsonValue = (
    str
    | int
    | float
    | bool
    | None
    | list["_JsonValue"]
    | tuple["_JsonValue", ...]
    | dict[str, "_JsonValue"]
)


def test_recursive_json_alias_classifies_as_named_sort() -> None:
    t = classify(_JsonValue)
    assert t.sort == "_JsonValue"


def test_recursive_json_alias_round_trips_primitives() -> None:
    t = classify(_JsonValue)
    for value in ("hello", 42, 1.5, True, False, None):
        assert t.decode(t.encode(value)) == value


def test_recursive_json_alias_round_trips_nested_dict() -> None:
    t = classify(_JsonValue)
    src: object = {"a": 1, "b": {"c": [1, 2, 3], "d": None}, "e": True}
    decoded = t.decode(t.encode(src))
    # lists become tuples on decode (FieldValue is tuple-based, not list)
    assert decoded == {"a": 1, "b": {"c": (1, 2, 3), "d": None}, "e": True}


def test_recursive_json_alias_tuple_round_trips_as_tuple() -> None:
    t = classify(_JsonValue)
    src = (1, "x", (2, 3))
    decoded = t.decode(t.encode(src))
    assert decoded == (1, "x", (2, 3))


def test_recursive_json_alias_inside_dict_value() -> None:
    t = classify(dict[str, _JsonValue])
    src: dict[str, object] = {"k": [1, {"nested": "v"}]}
    decoded = t.decode(t.encode(src))
    assert decoded == {"k": (1, {"nested": "v"})}


def test_recursive_json_alias_optional() -> None:
    t = classify(_JsonValue | None)
    assert t.is_optional
    assert t.decode(t.encode(None)) is None
    assert t.decode(t.encode({"a": 1})) == {"a": 1}


def test_recursive_json_alias_from_json_coerces_lists_to_tuples() -> None:
    t = classify(_JsonValue)
    assert t.from_json([1, [2, 3]]) == (1, (2, 3))


type _BadRecursive = str | int | bytes | list["_BadRecursive"]
type _AliasedBool = bool


def test_recursive_alias_with_non_json_arm_rejected() -> None:
    # ``bytes`` is not in the JSON-shape allow-list; the recursive alias
    # is rejected rather than silently accepted.
    with pytest.raises(TypeNotSupportedError):
        classify(_BadRecursive)


def test_non_recursive_alias_unaffected() -> None:
    """Plain non-recursive aliases keep the existing unwrap-and-recurse path."""
    t = classify(_AliasedBool)
    assert t.sort == "Bool"


# -- recursive alias as a Model field --------------------------------------

import didactic.api as dx  # noqa: E402

type _Params = (
    str
    | int
    | float
    | bool
    | None
    | list["_Params"]
    | tuple["_Params", ...]
    | dict[str, "_Params"]
)


class _Variation(dx.Model):
    kind: str
    params: dict[str, _Params]


def test_recursive_json_alias_works_as_model_field() -> None:
    """The neume use case: ``dict[str, JsonValue]`` on a real Model."""
    v = _Variation(
        kind="transposition",
        params={"semitones": 5, "tags": ["a", "b"], "meta": {"v": 1.0}},
    )
    raw = v.model_dump_json()
    v2 = _Variation.model_validate_json(raw)
    # lists round-trip as tuples (FieldValue is tuple-based).
    assert v2.params["semitones"] == 5
    assert v2.params["tags"] == ("a", "b")
    assert v2.params["meta"] == {"v": 1.0}
