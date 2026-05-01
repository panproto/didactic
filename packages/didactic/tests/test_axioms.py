"""Tests for class-level ``__axioms__`` collection.

Axioms are collected from a Model's class body into
``cls.__class_axioms__`` by the metaclass, walking the MRO so derived
classes inherit base-class axioms. Both [didactic.api.Axiom][] instances
and bare strings are accepted as ``__axioms__`` entries.
"""

# Test class is registered via ``@dx.axiom`` decorator side effect.
# Tracked in panproto/didactic#1.
# pyright: reportUnusedClass=false

from __future__ import annotations

import pytest

import didactic.api as dx
from didactic.axioms._axioms import collect_class_axioms


# -- axiom() constructor -----------------------------------------------


def test_axiom_constructor_returns_axiom() -> None:
    a = dx.axiom("len(xs) > 0")
    assert isinstance(a, dx.Axiom)
    assert a.expr == "len(xs) > 0"
    assert a.message is None
    assert a.name is None


def test_axiom_with_message_and_name() -> None:
    a = dx.axiom("x > 0", message="x must be positive", name="positive_x")
    assert a.message == "x must be positive"
    assert a.name == "positive_x"


def test_axiom_is_frozen() -> None:
    """Axioms are immutable by design."""
    a = dx.axiom("x > 0")
    with pytest.raises((AttributeError, TypeError)):
        a.expr = "y > 0"  # type: ignore[misc]


# -- class-level collection --------------------------------------------


def test_class_with_no_axioms_has_empty_tuple() -> None:
    class Plain(dx.Model):
        x: int

    assert Plain.__class_axioms__ == ()


def test_class_with_axioms_collects_them() -> None:
    class Bounded(dx.Model):
        x: int
        __axioms__ = [
            dx.axiom("x > 0", message="must be positive"),
            dx.axiom("x < 100", message="must be small"),
        ]

    assert len(Bounded.__class_axioms__) == 2
    assert Bounded.__class_axioms__[0].expr == "x > 0"
    assert Bounded.__class_axioms__[1].expr == "x < 100"


def test_axioms_accept_bare_strings() -> None:
    """A string entry in ``__axioms__`` is wrapped into an Axiom."""

    class Bounded(dx.Model):
        x: int
        __axioms__ = ["x > 0", dx.axiom("x < 100")]

    axioms = Bounded.__class_axioms__
    assert axioms[0].expr == "x > 0"
    assert axioms[0].message is None
    assert axioms[1].expr == "x < 100"


def test_axioms_reject_unknown_types() -> None:
    """Anything that isn't an Axiom or str is rejected."""
    with pytest.raises(TypeError, match="must be didactic.Axiom or str"):

        class Bad(dx.Model):
            x: int
            __axioms__ = [42]  # type: ignore[list-item]


# -- inheritance -------------------------------------------------------


def test_axioms_inherit_from_base_class() -> None:
    """Derived classes inherit base-class axioms in MRO order."""

    class BaseModel(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x > 0")]

    class DerivedModel(BaseModel):
        y: int
        __axioms__ = [dx.axiom("y > 0")]

    axioms = DerivedModel.__class_axioms__
    exprs = [a.expr for a in axioms]
    # base axioms come first (declaration order across MRO)
    assert exprs == ["x > 0", "y > 0"]


def test_collect_class_axioms_walks_mro() -> None:
    """The collector walks the entire MRO, not just the immediate class."""

    class A(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x > 0")]

    class B(A):
        y: int

    class C(B):
        z: int
        __axioms__ = [dx.axiom("z > 0")]

    axioms = collect_class_axioms(C)
    assert [a.expr for a in axioms] == ["x > 0", "z > 0"]


# -- theory bridge -----------------------------------------------------


def test_axioms_make_it_to_class_attribute() -> None:
    """The metaclass populates ``__class_axioms__`` from ``__axioms__``."""

    class Pitched(dx.Model):
        pitch: int
        __axioms__ = [dx.axiom("0 <= pitch <= 127")]

    # ``__class_axioms__`` is the canonical metaclass-collected form
    assert Pitched.__class_axioms__[0].expr == "0 <= pitch <= 127"
