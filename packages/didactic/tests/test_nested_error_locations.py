"""Validation failures inside nested models are reported under the outer field.

A field typed as a Model, a tagged union, or a container of either
validates its value by constructing the inner instance. The inner
class's ``ValidationError`` is caught, each entry is re-located under the
field name, the outer class is named, and the outer model keeps
collecting its sibling fields' errors.
"""

from __future__ import annotations

from typing import Literal

import pytest

import didactic.api as dx


class Inner(dx.Model, extra="forbid"):
    mode: Literal["a", "b"] = "a"
    count: int = 1


class Kind(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    pass


class First(Kind):
    kind: Literal["first"] = "first"
    width: int = 1


class Outer(dx.Model, extra="forbid"):
    inner: Inner = dx.field(default_factory=Inner)
    choice: Kind = dx.field(default_factory=First)
    items: tuple[Inner, ...] = ()
    top: Literal["x"] = "x"


def test_scalar_mismatch_is_a_type_error_entry_with_the_field_loc() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Inner(count="3")  # type: ignore[arg-type]
    assert info.value.model is Inner
    assert info.value.entries[0].loc == ("count",)
    assert info.value.entries[0].type == "type_error"
    assert info.value.entries[0].msg == "expected int, got str"


def test_nested_model_errors_are_relocated_under_the_field() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Outer.model_validate({"inner": {"mode": "c"}, "top": "y"})
    e = info.value
    assert e.model is Outer
    assert [(entry.loc, entry.type) for entry in e.entries] == [
        (("inner", "mode"), "type_error"),
        (("top",), "type_error"),
    ]
    assert "Outer" in str(e)
    assert "inner.mode" in str(e)


def test_nested_model_errors_are_relocated_from_json_too() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Outer.model_validate_json('{"inner": {"count": "3"}, "top": "y"}')
    e = info.value
    assert e.model is Outer
    assert [entry.loc for entry in e.entries] == [("inner", "count"), ("top",)]


def test_variant_errors_are_relocated_under_the_union_field() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Outer.model_validate({"choice": {"kind": "first", "width": "wide"}})
    e = info.value
    assert e.model is Outer
    assert e.entries[0].loc == ("choice", "width")
    assert e.entries[0].type == "type_error"


def test_container_element_errors_are_relocated_under_the_field() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Outer.model_validate({"items": [{"mode": "a"}, {"mode": "z"}]})
    e = info.value
    assert e.model is Outer
    assert e.entries[0].loc[0] == "items"
    assert e.entries[0].loc[-1] == "mode"


def test_with_relocates_nested_errors_too() -> None:
    outer = Outer()
    with pytest.raises(dx.ValidationError) as info:
        outer.with_(inner={"mode": "c"})
    e = info.value
    assert e.model is Outer
    assert e.entries[0].loc == ("inner", "mode")
