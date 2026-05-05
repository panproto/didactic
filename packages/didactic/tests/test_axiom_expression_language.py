"""Full panproto expression-language coverage for axioms.

Pins the v0.5.1 evaluator scope: every form documented in
``didactic.axioms._axiom_enforcement`` should round-trip through a
``__axioms__`` declaration, with the Python-friendly preprocessor
translating ``!=``, ``and``/``or``, ``null``/``None``, and
``is null`` / ``is not null`` to panproto's spellings.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue
from didactic.axioms._axiom_enforcement import (
    parse_axiom_predicate,
    preprocess_axiom_source,
)


# -- preprocessor --------------------------------------------------------


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("a != b", "a /= b"),
        ("a == null", "a == Nothing"),
        ("a == None", "a == Nothing"),
        ("a is null", "a == Nothing"),
        ("a is not null", "a /= Nothing"),
        ("a and b", "a && b"),
        ("a or b", "a || b"),
        # multiple substitutions in one expression
        ("a is null and b != null", "a == Nothing && b /= Nothing"),
    ],
)
def test_preprocessor_python_to_panproto(src: str, expected: str) -> None:
    assert preprocess_axiom_source(src) == expected


def test_preprocessor_respects_string_literals() -> None:
    """Substitutions don't fire inside ``"..."`` or ``'...'`` strings."""
    src = "tag != \"is not null\" and msg /= 'a or b'"
    out = preprocess_axiom_source(src)
    # The outer ``!=`` and ``and`` are rewritten; the string contents stay.
    assert out == "tag /= \"is not null\" && msg /= 'a or b'"


def test_preprocessor_handles_escaped_quotes() -> None:
    """Backslash-escaped quotes inside a string don't end the literal early."""
    src = r'a != "x \"and\" y"'
    out = preprocess_axiom_source(src)
    assert out == r'a /= "x \"and\" y"'


# -- null / Optional axioms (the issue's repro) --------------------------


class _Cfg(dx.Model):
    a: int | None = None
    b: str | None = None
    __axioms__ = (dx.axiom("a == null or b != null", message="a requires b"),)


def test_optional_axiom_holds_when_both_none() -> None:
    _Cfg(a=None, b=None)


def test_optional_axiom_holds_when_b_set() -> None:
    _Cfg(a=1, b="x")


def test_optional_axiom_fails_when_a_set_without_b() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _Cfg(a=1)
    assert exc.value.entries[0].msg == "a requires b"


# -- the spelled-out forms all work -------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "a == null or b != null",
        "a == None or b /= None",
        "a is null or b is not null",
        "a == Nothing || b /= Nothing",
    ],
)
def test_alternate_spellings_all_evaluate(expr: str) -> None:
    """Every Python-friendly spelling routes to the same panproto AST."""
    pred = parse_axiom_predicate(dx.axiom(expr))
    assert pred({"a": None, "b": None}) is True
    assert pred({"a": 1, "b": "x"}) is True
    assert pred({"a": 1, "b": None}) is False


# -- arithmetic and comparison ------------------------------------------


def test_arithmetic_and_comparison() -> None:
    pred = parse_axiom_predicate(dx.axiom("a + b * 2 > c"))
    assert pred({"a": 1, "b": 3, "c": 5}) is True
    assert pred({"a": 1, "b": 1, "c": 10}) is False


# -- if/then/else (Match) -----------------------------------------------


def test_if_then_else() -> None:
    pred = parse_axiom_predicate(dx.axiom("if bounded then min /= null else true"))
    assert pred({"bounded": True, "min": 0, "true": True}) is True
    assert pred({"bounded": True, "min": None, "true": True}) is False
    assert pred({"bounded": False, "min": None, "true": True}) is True


# -- App-style builtins (min, max, abs, len) ----------------------------


def test_min_max_abs_via_app() -> None:
    assert parse_axiom_predicate(dx.axiom("min a b == 1"))({"a": 1, "b": 2}) is True
    assert parse_axiom_predicate(dx.axiom("max a b == 2"))({"a": 1, "b": 2}) is True
    assert parse_axiom_predicate(dx.axiom("abs (a - b) == 3"))({"a": 1, "b": 4}) is True


def test_len_works() -> None:
    pred = parse_axiom_predicate(dx.axiom("len xs > 0"))
    assert pred({"xs": (1, 2, 3)}) is True
    assert pred({"xs": ()}) is False


# -- list literal + elem -------------------------------------------------


def test_list_literal_and_elem() -> None:
    pred = parse_axiom_predicate(dx.axiom("elem x [1, 2, 3]"))
    assert pred({"x": 2}) is True
    assert pred({"x": 5}) is False


# -- list / string concatenation (++) ------------------------------------


def test_concat() -> None:
    pred = parse_axiom_predicate(dx.axiom('xs ++ ys == "abdef"'))
    assert pred({"xs": "ab", "ys": "def"}) is True


# -- Field access (a.b) -------------------------------------------------


def test_field_access() -> None:
    """``a.b`` resolves via getattr."""

    class _Box:
        def __init__(self, n: int) -> None:
            self.n = n

    pred = parse_axiom_predicate(dx.axiom("box.n == 7"))
    assert pred(cast("dict[str, FieldValue]", {"box": _Box(7)})) is True
    assert pred(cast("dict[str, FieldValue]", {"box": _Box(0)})) is False


# -- let bindings -------------------------------------------------------


def test_let_binding() -> None:
    pred = parse_axiom_predicate(dx.axiom("let s = a + b in s > 0"))
    assert pred({"a": 1, "b": 2}) is True
    assert pred({"a": -5, "b": 3}) is False


# -- map / filter (with lambda or builtin) ------------------------------


def test_map_with_lambda() -> None:
    pred = parse_axiom_predicate(dx.axiom("len (map (\\x -> x + 1) xs) == 3"))
    assert pred(cast("dict[str, FieldValue]", {"xs": [1, 2, 3]})) is True


def test_filter_with_lambda() -> None:
    pred = parse_axiom_predicate(dx.axiom("len (filter (\\x -> x > 0) xs) == 2"))
    assert pred(cast("dict[str, FieldValue]", {"xs": [-1, 1, 2]})) is True


# -- Just / Nothing -----------------------------------------------------


def test_just_unwraps() -> None:
    pred = parse_axiom_predicate(dx.axiom("Just x == y"))
    assert pred({"x": 5, "y": 5}) is True


def test_nothing_compares_to_none() -> None:
    pred = parse_axiom_predicate(dx.axiom("a == Nothing"))
    assert pred({"a": None}) is True
    assert pred({"a": 1}) is False


# -- error cases --------------------------------------------------------


def test_unknown_function_raises_clear_error() -> None:
    """An unrecognised function name surfaces as a validation failure."""

    class _M(dx.Model):
        x: int = 0
        __axioms__ = (dx.axiom("zarquon x == 0"),)

    with pytest.raises(dx.ValidationError) as exc:
        _M(x=0)
    assert "cannot evaluate" in exc.value.entries[0].msg


# -- regression: existing axioms still pass -----------------------------


class _Range(dx.Model):
    low: int = 0
    high: int = 10
    __axioms__ = (dx.axiom("low <= high"),)


def test_existing_arithmetic_axiom_still_works() -> None:
    _Range(low=0, high=10)
    with pytest.raises(dx.ValidationError):
        _Range(low=5, high=3)


def test_axiom_record_is_immutable() -> None:
    """Axiom is a frozen dataclass; ``replace`` produces a new record."""
    a = dx.axiom("x == 0")
    b = replace(a, message="x must be zero")
    assert a.expr == b.expr
    assert b.message == "x must be zero"
