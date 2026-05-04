"""Tests for Pydantic-parity additions: model_dump options, RootModel, TypeAdapter."""

# Test calls a Model with the field name when the test's Model
# declares an alias; pyright reads the alias as the parameter name
# while the runtime accepts both. Tracked in panproto/didactic#1.

from __future__ import annotations

import didactic.api as dx

# -- model_dump options ----------------------------------------------


class _DumpModel(dx.Model):
    a: int
    b: str = "default_b"
    c: int | None = None


def test_model_dump_basic() -> None:
    m = _DumpModel(a=1, b="hello", c=42)
    assert m.model_dump() == {"a": 1, "b": "hello", "c": 42}


def test_model_dump_include() -> None:
    m = _DumpModel(a=1, b="hello", c=42)
    assert m.model_dump(include={"a", "b"}) == {"a": 1, "b": "hello"}


def test_model_dump_exclude() -> None:
    m = _DumpModel(a=1, b="hello", c=42)
    assert m.model_dump(exclude={"c"}) == {"a": 1, "b": "hello"}


def test_model_dump_exclude_none() -> None:
    m = _DumpModel(a=1, b="hello")
    assert m.model_dump(exclude_none=True) == {"a": 1, "b": "hello"}


def test_model_dump_exclude_defaults() -> None:
    m = _DumpModel(a=1)
    assert m.model_dump(exclude_defaults=True) == {"a": 1}


def test_model_dump_by_alias() -> None:
    class M(dx.Model):
        user_id: str = dx.field(alias="userId")
        email: str

    m = M.model_validate({"user_id": "u1", "email": "a@b.c"})
    assert m.model_dump(by_alias=True) == {"userId": "u1", "email": "a@b.c"}
    assert m.model_dump(by_alias=False) == {"user_id": "u1", "email": "a@b.c"}


# -- TypeAdapter -----------------------------------------------------


def test_type_adapter_int() -> None:
    a = dx.TypeAdapter(int)
    assert a.validate(42) == 42


def test_type_adapter_str() -> None:
    a = dx.TypeAdapter(str)
    assert a.validate("hello") == "hello"


def test_type_adapter_dump_json() -> None:
    a = dx.TypeAdapter(int)
    assert a.dump_json(42) == '"42"' or a.dump_json(42) == "42"


# -- @dx.derived ----------------------------------------------------


def test_derived_basic() -> None:
    class Box(dx.Model):
        w: int
        h: int

        @dx.derived
        def area(self) -> int:
            return self.w * self.h

    b = Box(w=3, h=4)
    assert b.area == 12


def test_derived_is_cached() -> None:
    """Derived values are computed once per instance."""
    call_count = [0]

    class M(dx.Model):
        x: int

        @dx.derived
        def doubled(self) -> int:
            call_count[0] += 1
            return self.x * 2

    m = M(x=5)
    assert m.doubled == 10
    assert m.doubled == 10
    assert m.doubled == 10
    # the function should only run once because of the cache
    assert call_count[0] == 1


def test_derived_appears_in_dump() -> None:
    class Person(dx.Model):
        first: str
        last: str

        @dx.derived
        def display_name(self) -> str:
            return f"{self.first} {self.last}"

    p = Person(first="Ada", last="Lovelace")
    dump = p.model_dump()
    assert dump["display_name"] == "Ada Lovelace"


def test_derived_round_trip_through_dump() -> None:
    """A model with a derived field round-trips through model_validate(model_dump())."""

    class Person(dx.Model):
        first: str
        last: str

        @dx.derived
        def display_name(self) -> str:
            return f"{self.first} {self.last}"

    p = Person(first="Grace", last="Hopper")
    payload = p.model_dump()
    back = Person.model_validate(payload)
    assert back.first == "Grace"
    assert back.display_name == "Grace Hopper"
