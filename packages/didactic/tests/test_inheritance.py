# Tests build a set of Model classes for assertions on theory
# inheritance; pyright flags ``set`` literals containing classes as
# unhashable (Model is hashable by class identity at runtime). Also
# compares ``len()`` results returned by didactic helpers that
# pyright sees as ``() -> int`` rather than ``int`` due to the
# ``__class_axioms__`` decorator wrapper. Tracked in
# panproto/didactic#1.
# pyright: reportUnhashable=false, reportOperatorIssue=false
"""Tests for Theory construction with class inheritance.

Single inheritance flattens transparently (the metaclass walks the
MRO when collecting field specs). Multiple inheritance triggers a
real ``panproto.colimit_theories`` call.
"""

from __future__ import annotations

import panproto

import didactic.api as dx
from didactic.theory._theory import build_theory, build_theory_spec


# -- single inheritance ------------------------------------------------


def test_single_inheritance_flattens_fields() -> None:
    class A(dx.Model):
        x: int

    class B(A):
        y: int

    spec = build_theory_spec(B)
    op_names = {op["name"] for op in spec["ops"]}
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
    assert theory.op_count >= 4


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
    assert theory.op_count >= 3
