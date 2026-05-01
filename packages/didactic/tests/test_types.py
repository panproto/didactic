"""Unit tests for the type-translation foundation."""

# Tests pass ``Annotated[T, ...]`` forms to ``classify`` and
# ``unwrap_annotated``; the static ``TypeForm`` alias doesn't
# include ``Annotated`` (a typing special form, not a class), but
# the runtime accepts it. Tracked in panproto/didactic#1.
# pyright: reportArgumentType=false

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal, cast
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


# -- PEP 695 type aliases --------------------------------------------------

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


# -- union of primitives ---------------------------------------------------


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


# -- recursive JSON-shaped type aliases ------------------------------------

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


# -- Model-ref recursive type aliases (planned for v0.3.0) -----------------
#
# A recursive alias whose body mixes primitive scalars, JSON-compatible
# containers, and ``dx.Model`` subclasses. Encoded by walking the value
# and replacing each Model instance with a ``$schema``-tagged envelope so
# the decoder can dispatch to the right ``Model.model_validate``. See
# ``notes/plan-model-ref-recursive-aliases.md`` for the full design.


class _Heading(dx.Model):
    text: str
    level: int = 1


class _Paragraph(dx.Model):
    text: str


type _Component = (
    str
    | int
    | float
    | bool
    | None
    | _Heading
    | _Paragraph
    | list["_Component"]
    | tuple["_Component", ...]
    | dict[str, "_Component"]
)


def test_model_ref_alias_classifies_as_named_sort() -> None:
    t = classify(_Component)
    assert t.sort == "_Component"


def test_model_ref_alias_round_trips_primitive_arm() -> None:
    t = classify(_Component)
    for value in ("hello", 42, 1.5, True, None):
        assert t.decode(t.encode(value)) == value


def test_model_ref_alias_round_trips_single_model() -> None:
    t = classify(_Component)
    h = _Heading(text="Intro", level=2)
    decoded = t.decode(t.encode(h))
    assert isinstance(decoded, _Heading)
    assert decoded == h


def test_model_ref_alias_round_trips_list_of_models() -> None:
    t = classify(_Component)
    src = [_Heading(text="A"), _Paragraph(text="B"), _Heading(text="C")]
    decoded = t.decode(t.encode(src))
    # lists round-trip as tuples (FieldValue invariant)
    assert decoded == (
        _Heading(text="A"),
        _Paragraph(text="B"),
        _Heading(text="C"),
    )


def test_model_ref_alias_dict_with_mixed_arms() -> None:
    t = classify(_Component)
    src = {
        "title": _Heading(text="Doc", level=1),
        "intro": _Paragraph(text="Welcome"),
        "count": 7,
        "tags": ["a", "b"],
    }
    decoded = t.decode(t.encode(src))
    assert decoded == {
        "title": _Heading(text="Doc", level=1),
        "intro": _Paragraph(text="Welcome"),
        "count": 7,
        "tags": ("a", "b"),
    }


def test_model_ref_alias_nested_model_in_dict_in_list() -> None:
    t = classify(_Component)
    src = [{"item": _Paragraph(text="nested")}]
    decoded = t.decode(t.encode(src))
    assert decoded == ({"item": _Paragraph(text="nested")},)


def test_model_ref_alias_constructor_tag_format() -> None:
    """The encoded value uses panproto-style constructor tags.

    Each variant produces a single-key JSON object whose key is the
    constructor name in the alias's closed sum sort, and whose value is
    the constructor's payload. This matches the wire shape panproto
    expects for ``Term::Case`` over a closed sort.
    """
    import json as _json

    t = classify(_Component)
    # Model variant
    raw_obj = _json.loads(t.encode(_Heading(text="X", level=3)))
    assert raw_obj == {"_Component_heading": {"text": "X", "level": 3}}
    # primitive variant
    assert _json.loads(t.encode(42)) == {"_Component_int": 42}


def test_model_ref_alias_rejects_unknown_constructor() -> None:
    """A bogus constructor tag in a payload fails decode with a clear error."""
    import json as _json

    t = classify(_Component)
    bogus = _json.dumps({"not_a_constructor": {"x": 1}})
    with pytest.raises((KeyError, ValueError, TypeError)):
        t.decode(bogus)


class _Plain:
    """Non-Model class used to test the negative-rejection path."""


type _BadAlias = str | _Plain | list["_BadAlias"]


def test_model_ref_alias_rejects_non_model_class_arm() -> None:
    """A recursive alias with a plain (non-Model) class arm is rejected."""
    with pytest.raises(TypeNotSupportedError):
        classify(_BadAlias)


def test_model_ref_alias_cycle_raises() -> None:
    """A value graph that loops through the alias raises rather than recurse."""
    t = classify(_Component)
    # construct a cycle by mutating the underlying dict after it's stored;
    # Models are frozen, so the cycle has to live on a container value
    inner: dict[str, object] = {"a": 1}
    inner["self"] = inner
    with pytest.raises((RecursionError, ValueError)):
        t.encode(inner)


def test_model_ref_alias_works_as_model_field() -> None:
    """Integration: a Model with a model-ref recursive field round-trips."""

    class _Document(dx.Model):
        title: str
        body: _Component

    d = _Document(
        title="Spec",
        body=[
            _Heading(text="Overview", level=1),
            _Paragraph(text="This is the overview."),
            {"meta": {"version": 1}},
        ],
    )
    raw = d.model_dump_json()
    d2 = _Document.model_validate_json(raw)
    assert d2.title == "Spec"
    assert d2.body == (
        _Heading(text="Overview", level=1),
        _Paragraph(text="This is the overview."),
        {"meta": {"version": 1}},
    )


# -- alias contributes a closed sum sort to the parent Theory --------------


class _DocWithComponent(dx.Model):
    body: _Component


def test_alias_emits_closed_sum_sort_in_parent_theory_spec() -> None:
    """The parent Model's Theory spec contains the alias's closed sum sort."""
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_DocWithComponent)
    sorts_by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    # alias sum sort is present
    assert "_Component" in sorts_by_name
    component = sorts_by_name["_Component"]
    assert component["kind"] == "Structural"
    closure = cast("dict[str, list[str]]", component["closure"])
    assert "Closed" in closure
    # constructors include one per primitive arm + one per Model arm + the
    # container shapes the alias actually uses
    constructors = set(closure["Closed"])
    assert "_Component_str" in constructors
    assert "_Component_int" in constructors
    assert "_Component_heading" in constructors
    assert "_Component_paragraph" in constructors
    assert "_Component_list" in constructors
    assert "_Component_tuple" in constructors
    assert "_Component_dict" in constructors


def test_alias_constructors_are_operations_returning_alias_sort() -> None:
    """Every constructor name appears as an Op whose output is the alias sort."""
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_DocWithComponent)
    ops_by_name = {cast("str", op["name"]): op for op in spec["ops"]}
    expected_constructors = [
        "_Component_str",
        "_Component_int",
        "_Component_heading",
        "_Component_paragraph",
        "_Component_list",
        "_Component_tuple",
        "_Component_dict",
    ]
    for tag in expected_constructors:
        assert tag in ops_by_name, f"missing constructor op {tag}"
        assert ops_by_name[tag]["output"] == "_Component"


def test_alias_field_accessor_returns_alias_sort() -> None:
    """The field accessor for a sum-sort field outputs the alias sum sort."""
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_DocWithComponent)
    ops_by_name = {cast("str", op["name"]): op for op in spec["ops"]}
    assert ops_by_name["body"]["output"] == "_Component"


def test_panproto_accepts_alias_theory_spec() -> None:
    """panproto's ``create_theory`` accepts the spec with the alias sorts.

    Verifies that the closed sum sort + helper sorts + constructor ops
    deserialise into a real ``panproto.Theory`` without error. The
    ``Theory.sorts`` attribute is a list of sort dicts at runtime
    (the stub claims it's a method; treat as data).
    """
    import panproto

    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_DocWithComponent)
    theory = panproto.create_theory(cast("dict[str, object]", spec))
    sort_records = cast("list[dict[str, object]]", theory.sorts)
    sort_names = {cast("str", record["name"]) for record in sort_records}
    assert "_Component" in sort_names
