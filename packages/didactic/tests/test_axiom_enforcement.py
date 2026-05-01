"""Tests for axiom enforcement at construction time."""

# Dynamically constructs a Model class via ``Model.__class__``
# metaclass invocation; pyright can't follow the call shape.
# Tracked in panproto/didactic#1.
# pyright: reportCallIssue=false

from __future__ import annotations

import pytest

import didactic.api as dx


# -- simple axioms ----------------------------------------------------


def test_axiom_passes_when_satisfied() -> None:
    class Pos(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x > 0")]

    p = Pos(x=5)
    assert p.x == 5


def test_axiom_raises_validation_error_when_violated() -> None:
    class Pos(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x > 0")]

    with pytest.raises(dx.ValidationError, match="axiom failed"):
        Pos(x=0)


def test_axiom_uses_custom_message() -> None:
    class Pos(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x > 0", message="x must be positive")]

    with pytest.raises(dx.ValidationError, match="x must be positive"):
        Pos(x=-1)


# -- compound axioms --------------------------------------------------


def test_two_axioms_both_enforced() -> None:
    class Range(dx.Model):
        low: int
        high: int
        __axioms__ = [
            dx.axiom("low >= 0", message="low must be non-negative"),
            dx.axiom("low <= high", message="low must not exceed high"),
        ]

    Range(low=0, high=10)
    Range(low=3, high=3)

    with pytest.raises(dx.ValidationError, match="low must be non-negative"):
        Range(low=-1, high=5)

    with pytest.raises(dx.ValidationError, match="low must not exceed high"):
        Range(low=10, high=5)


# -- supported operators ---------------------------------------------


@pytest.mark.parametrize(
    ("expr", "value", "should_pass"),
    [
        ("x > 0", 1, True),
        ("x > 0", 0, False),
        ("x >= 0", 0, True),
        ("x >= 0", -1, False),
        ("x < 10", 9, True),
        ("x < 10", 10, False),
        ("x <= 10", 10, True),
        ("x <= 10", 11, False),
        ("x == 42", 42, True),
        ("x == 42", 41, False),
        ("x /= 0", 1, True),
        ("x /= 0", 0, False),
    ],
)
def test_comparison_operators(
    expr: str,
    value: int,
    should_pass: bool,
) -> None:
    cls = dx.Model.__class__(  # type: ignore[call-overload]
        "Cls",
        (dx.Model,),
        {"__annotations__": {"x": int}, "__axioms__": [dx.axiom(expr)]},
    )
    if should_pass:
        cls(x=value)
    else:
        with pytest.raises(dx.ValidationError):
            cls(x=value)


# -- inherited axioms enforced on derived class ----------------------


def test_inherited_axioms_enforced() -> None:
    class Base(dx.Model):
        x: int
        __axioms__ = [dx.axiom("x >= 0", message="x must be non-negative")]

    class Derived(Base):
        y: int

    Derived(x=1, y=42)
    with pytest.raises(dx.ValidationError, match="x must be non-negative"):
        Derived(x=-1, y=42)


# -- model with no axioms is unaffected ------------------------------


def test_no_axioms_no_overhead() -> None:
    class Plain(dx.Model):
        x: int

    p = Plain(x=-1)
    assert p.x == -1
