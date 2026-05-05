# Tests build a set of Model classes for assertions on theory
# inheritance; pyright flags ``set`` literals containing classes as
# unhashable (Model is hashable by class identity at runtime). Also
# compares ``len()`` results returned by didactic helpers that
# pyright sees as ``() -> int`` rather than ``int`` due to the
# ``__class_axioms__`` decorator wrapper. Tracked in
# panproto/didactic#1.
"""Tests for Theory construction with class inheritance.

Single inheritance flattens transparently (the metaclass walks the
MRO when collecting field specs). Multiple inheritance triggers a
real ``panproto.colimit_theories`` call.
"""

from __future__ import annotations

from typing import Protocol, cast

import panproto
import pytest

import didactic.api as dx
from didactic.theory._theory import build_theory, build_theory_spec


class _TheoryShape(Protocol):
    """Property-shaped view of ``panproto.Theory`` count attributes.

    The upstream stub still types ``op_count`` / ``sort_count`` /
    ``eq_count`` as zero-arg methods; at runtime they are properties.
    Casting through this protocol lets the tests express the property
    semantics without bypassing the type checker.
    """

    @property
    def op_count(self) -> int: ...
    @property
    def sort_count(self) -> int: ...
    @property
    def eq_count(self) -> int: ...


# -- single inheritance ------------------------------------------------


def test_single_inheritance_flattens_fields() -> None:
    class A(dx.Model):
        x: int

    class B(A):
        y: int

    spec = build_theory_spec(B)
    op_names = {cast("str", op["name"]) for op in spec["ops"]}
    assert op_names == {"x", "y"}


def test_single_inheritance_builds_panproto_theory() -> None:
    class A(dx.Model):
        x: int

    class B(A):
        y: int

    theory = build_theory(B)
    assert isinstance(theory, panproto.Theory)
    assert theory.op_count == 2


def test_three_level_chain_flattens() -> None:
    class A(dx.Model):
        x: int

    class B(A):
        y: int

    class C(B):
        z: int

    theory = build_theory(C)
    assert theory.op_count == 3


# -- multiple inheritance ----------------------------------------------


def test_diamond_inheritance_uses_colimit() -> None:
    """A diamond inheritance pattern produces a Theory via colimit.

    The merge has three branches:

    .. code-block:: text

           A
          / \\
         B   C
          \\ /
           D
    """

    class A(dx.Model):
        shared: int

    class B(A):
        b_only: int

    class C(A):
        c_only: int

    class D(B, C):
        d_only: int

    theory = build_theory(D)
    assert isinstance(theory, panproto.Theory)
    # colimit pushes out B and C over A; resulting Theory has all
    # accessor ops from the four classes but the ``shared`` accessor
    # only appears once
    # ``op_count`` is a property at runtime; the panproto stub still
    # types it as a zero-arg method. ``_TheoryShape`` projects the
    # property view we rely on.
    assert cast("_TheoryShape", theory).op_count >= 4


def test_two_unrelated_parents_uses_colimit() -> None:
    """Combining two independent Model lineages."""

    class A(dx.Model):
        a: int

    class B(dx.Model):
        b: int

    class C(A, B):
        c: int

    theory = build_theory(C)
    assert isinstance(theory, panproto.Theory)
    # ops from A, B, and the cls-only c
    assert cast("_TheoryShape", theory).op_count >= 3


# -- inherited-default propagation ----------------------------------------


class _Base(dx.Model):
    """Parent with both plain and factory defaults on every field."""

    id: str = "default-id"
    name: str = "default-name"


class _Child(_Base):
    """Adds one own field; should inherit ``id`` and ``name`` defaults."""

    extra: str = "x"


def test_subclass_inherits_parent_defaults() -> None:
    """A subclass picks up the parent's field defaults."""
    child = _Child()
    assert child.id == "default-id"
    assert child.name == "default-name"
    assert child.extra == "x"


def test_subclass_overrides_inherited_default() -> None:
    """The user can still override an inherited default at construction."""
    child = _Child(id="explicit", name="other")
    assert child.id == "explicit"
    assert child.name == "other"
    assert child.extra == "x"


def test_default_factory_inherited_per_call() -> None:
    """``default_factory`` on a parent runs fresh on each subclass instance."""

    counter = {"n": 0}

    def _next() -> int:
        counter["n"] += 1
        return counter["n"]

    class _BaseWithFactory(dx.Model):
        seq: int = dx.field(default_factory=_next)

    class _ChildWithFactory(_BaseWithFactory):
        tag: str = "t"

    a = _ChildWithFactory()
    b = _ChildWithFactory()
    assert a.seq == 1
    assert b.seq == 2
    assert a.tag == b.tag == "t"


def test_subclass_can_override_inherited_field_with_new_default() -> None:
    """Re-declaring an inherited field on the subclass overwrites the spec."""

    class _OverridingChild(_Base):
        # override the parent's default for ``id``
        id: str = "child-default"

    child = _OverridingChild()
    assert child.id == "child-default"
    assert child.name == "default-name"


def test_three_level_chain_propagates_defaults() -> None:
    """Defaults flow through more than one level of inheritance."""

    class _A(dx.Model):
        a: str = "a-default"

    class _B(_A):
        b: str = "b-default"

    class _C(_B):
        c: str = "c-default"

    instance = _C()
    assert instance.a == "a-default"
    assert instance.b == "b-default"
    assert instance.c == "c-default"


def test_inherited_required_field_still_required_on_subclass() -> None:
    """A required parent field stays required on the subclass."""

    class _RequiredBase(dx.Model):
        name: str  # no default

    class _ChildOfRequired(_RequiredBase):
        extra: str = "x"

    with pytest.raises(dx.ValidationError) as exc:
        _ChildOfRequired.model_validate({})
    assert any(e.type == "missing_required" for e in exc.value.entries)
