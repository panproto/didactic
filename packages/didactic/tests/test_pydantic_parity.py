"""Tests for Pydantic-parity additions: model_dump options, RootModel, TypeAdapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
from didactic.fields import _derived

if TYPE_CHECKING:
    import pytest

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


def test_derived_field_names_cached_on_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The derived-name tuple is materialised once per class, not per instance.

    ``derived_field_names`` is a pure function of the class, so the
    metaclass computes it at class-creation time and stores it as
    ``__derived_field_names__``. ``Model.__init__`` and ``model_dump``
    read that cached tuple; neither recomputes it, so constructing and
    dumping never re-walk the MRO.
    """

    class Base(dx.Model):
        first: str
        last: str

        @dx.derived
        def full(self) -> str:
            return f"{self.first} {self.last}"

    class Sub(Base):
        title: str

        @dx.derived
        def formal(self) -> str:
            return f"{self.title} {self.full}"

    assert Base.__derived_field_names__ == ("full",)
    assert set(Sub.__derived_field_names__) == {"full", "formal"}

    calls = 0
    original = _derived.derived_field_names

    def counting(cls: type) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return original(cls)

    monkeypatch.setattr(_derived, "derived_field_names", counting)

    for _ in range(100):
        instance = Sub(first="Ada", last="Lovelace", title="Dr")
        assert instance.model_dump()["formal"] == "Dr Ada Lovelace"

    # construction + dump read the cached tuple; the walker never runs
    assert calls == 0
