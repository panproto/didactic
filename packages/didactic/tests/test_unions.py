"""Tests for ``dx.TaggedUnion`` discriminated unions."""

# Test classes inside test functions are registered via the
# ``TaggedUnion`` metaclass side effect; the local name is "unused"
# from a pyright POV. Tracked in panproto/didactic#1.

from typing import Literal

import pytest

import didactic.api as dx

# -- a representative union ----------------------------------------------


class Shape(dx.TaggedUnion, discriminator="kind"):
    """Sum-type root; subclasses are the variants."""


class Circle(Shape):
    kind: Literal["circle"]
    radius: float


class Square(Shape):
    kind: Literal["square"]
    side: float


class Triangle(Shape):
    kind: Literal["triangle"]
    base: float
    height: float


# -- registration --------------------------------------------------------


def test_root_records_discriminator() -> None:
    assert Shape.__discriminator__ == "kind"


def test_variants_registered_under_root() -> None:
    assert set(Shape.__variants__) == {"circle", "square", "triangle"}
    assert Shape.__variants__["circle"] is Circle
    assert Shape.__variants__["square"] is Square
    assert Shape.__variants__["triangle"] is Triangle


# -- dispatch ------------------------------------------------------------


def test_validate_dispatches_to_variant() -> None:
    s = Shape.model_validate({"kind": "circle", "radius": 1.5})
    assert isinstance(s, Circle)
    assert s.radius == 1.5


def test_validate_dispatches_each_variant() -> None:
    sq = Shape.model_validate({"kind": "square", "side": 3.0})
    tri = Shape.model_validate({"kind": "triangle", "base": 4.0, "height": 5.0})
    assert isinstance(sq, Square)
    assert isinstance(tri, Triangle)
    assert sq.side == 3.0
    assert tri.base == 4.0
    assert tri.height == 5.0


def test_validate_unknown_discriminator() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        Shape.model_validate({"kind": "hex", "n": 6})
    assert any(e.type == "unknown_discriminator" for e in exc.value.entries)


def test_validate_missing_discriminator() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        Shape.model_validate({"radius": 1.0})
    assert any(e.type == "missing_discriminator" for e in exc.value.entries)


# -- variant constructed directly --------------------------------------


def test_variant_constructed_directly() -> None:
    c = Circle(kind="circle", radius=2.0)
    assert c.radius == 2.0
    assert c.kind == "circle"


def test_variant_validate_does_not_dispatch() -> None:
    # When validating against a variant directly, no dispatch happens
    c = Circle.model_validate({"kind": "circle", "radius": 2.0})
    assert isinstance(c, Circle)


# -- JSON round trip ----------------------------------------------------


def test_json_round_trip_via_root_dispatch() -> None:
    src = Shape.model_validate({"kind": "square", "side": 7.0})
    raw = src.model_dump_json()
    out = Shape.model_validate_json(raw)
    assert isinstance(out, Square)
    assert out.side == 7.0
    assert out == src


# -- duplicate registration error -------------------------------------


def test_duplicate_discriminator_value_rejected() -> None:
    class Sound(dx.TaggedUnion, discriminator="kind"):
        pass

    class Bark(Sound):
        kind: Literal["bark"]

    assert Bark is not None  # registration side effect

    with pytest.raises(TypeError, match="already registered"):

        class Bark2(Sound):
            kind: Literal["bark"]

        assert Bark2 is not None  # registration is the test; class drops out


def test_variant_must_have_discriminator_field() -> None:
    class Animal(dx.TaggedUnion, discriminator="species"):
        pass

    with pytest.raises(TypeError, match="must declare"):

        class WithoutSpecies(Animal):
            name: str

        assert WithoutSpecies is not None  # registration is the test


def test_variant_discriminator_must_be_literal() -> None:
    class Mode(dx.TaggedUnion, discriminator="kind"):
        pass

    with pytest.raises(TypeError, match="Literal"):

        class Bad(Mode):
            kind: str

        assert Bad is not None  # registration is the test


# -- isolated registries between unions ------------------------------


def test_separate_unions_have_separate_registries() -> None:
    class A(dx.TaggedUnion, discriminator="kind"):
        pass

    class A1(A):
        kind: Literal["one"]

    class B(dx.TaggedUnion, discriminator="kind"):
        pass

    class B1(B):
        kind: Literal["one"]

    # the same discriminator value appears in both unions without conflict
    assert A.__variants__ == {"one": A1}
    assert B.__variants__ == {"one": B1}
