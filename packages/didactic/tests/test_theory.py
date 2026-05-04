# Tests build sets of Model classes for theory-equivalence checks;
# pyright flags ``set`` literals containing classes as unhashable
# (Model is hashable by class identity at runtime). Tracked in
# panproto/didactic#1.
"""Tests for the panproto-Theory bridge.

The bridge has two layers:

- ``build_theory_spec(cls)`` — pure-Python; produces the spec dict.
- ``build_theory(cls)`` — calls ``panproto.create_theory(spec)`` and
  returns a real ``panproto.Theory``.

We exercise both. The integration test loads ``panproto`` directly.
"""

from typing import cast

import panproto

import didactic.api as dx
from didactic.theory._theory import build_theory, build_theory_spec


class Simple(dx.Model):
    """Three-field model used across the spec-shape tests."""

    id: str
    age: int
    nickname: str | None = None


# -- spec shape (no panproto required) -----------------------------------


def test_spec_top_level_keys() -> None:
    spec = build_theory_spec(Simple)
    assert set(spec) == {
        "name",
        "extends",
        "sorts",
        "ops",
        "eqs",
        "directed_eqs",
        "policies",
    }


def test_spec_name_matches_class() -> None:
    spec = build_theory_spec(Simple)
    assert spec["name"] == "Simple"


def test_spec_primary_sort_present() -> None:
    spec = build_theory_spec(Simple)
    primary = next(s for s in spec["sorts"] if s["name"] == "Simple")
    # panproto's SortKind enum uses PascalCase variants
    assert primary["kind"] == "Structural"


def test_spec_per_field_constraint_sorts() -> None:
    spec = build_theory_spec(Simple)
    sort_names = {cast("str", s["name"]) for s in spec["sorts"]}
    assert "Simple_id" in sort_names
    assert "Simple_age" in sort_names
    assert "Simple_nickname" in sort_names


def test_spec_field_accessor_ops() -> None:
    spec = build_theory_spec(Simple)
    op_names = {cast("str", op["name"]) for op in spec["ops"]}
    assert op_names == {"id", "age", "nickname"}


def test_spec_value_kind_carried() -> None:
    spec = build_theory_spec(Simple)
    by_name = {s["name"]: s for s in spec["sorts"]}
    # the panproto-side ValueKind enum: String -> Str, Int -> Int.
    # Optional / container sorts collapse to Str (they're stringified
    # JSON in v0.0.2 — see _theory._VALUE_KIND_FOR_SORT).
    assert by_name["Simple_id"]["kind"] == {"Val": "Str"}
    assert by_name["Simple_age"]["kind"] == {"Val": "Int"}
    assert by_name["Simple_nickname"]["kind"] == {"Val": "Str"}


def test_spec_extends_empty_for_simple_model() -> None:
    spec = build_theory_spec(Simple)
    assert spec["extends"] == []


def test_spec_eqs_empty_for_simple_model() -> None:
    # axiom translation is deferred; the spec carries no equations yet
    spec = build_theory_spec(Simple)
    assert spec["eqs"] == []


# -- runtime (uses real panproto.Theory) ---------------------------------


def test_build_theory_returns_panproto_theory() -> None:
    theory = build_theory(Simple)
    assert isinstance(theory, panproto.Theory)
    assert theory.name == "Simple"
    assert theory.sort_count == 4  # primary + 3 constraint sorts
    assert theory.op_count == 3  # 3 field accessors
    assert theory.eq_count == 0


def test_model_theory_attribute_lazy() -> None:
    # Accessing __theory__ materialises and caches a panproto.Theory.
    t1 = Simple.__theory__
    assert isinstance(t1, panproto.Theory)
    # repeated access returns the same cached object
    t2 = Simple.__theory__
    assert t1 is t2


def test_class_axioms_collected_on_python_side() -> None:
    class Counter(dx.Model):
        n: int

        # creation time; the list-typed default never escapes the class body.
        __axioms__ = [
            dx.axiom("n >= 0", message="counter must be non-negative"),
        ]

    # axioms ARE collected on the class (Python-side surface)
    assert len(Counter.__class_axioms__) == 1
    assert Counter.__class_axioms__[0].expr == "n >= 0"
    assert Counter.__class_axioms__[0].message == "counter must be non-negative"
    # but the panproto-side Equation translation (surface syntax →
    # Term AST) is deferred to a later phase. Theory builds cleanly
    # with empty eqs for now.
    spec = build_theory_spec(Counter)
    assert spec["eqs"] == []
    theory = build_theory(Counter)
    assert isinstance(theory, panproto.Theory)
    assert theory.eq_count == 0


def test_theory_with_ref_emits_edge() -> None:
    class Target(dx.Model):
        id: str

    class Holder(dx.Model):
        id: str
        target: dx.Ref[Target]

    spec = build_theory_spec(Holder)
    op_by_name = {op["name"]: op for op in spec["ops"]}
    # the ref op outputs the target's primary sort (a bare string,
    # matching panproto's untagged SortExpr representation)
    assert op_by_name["target"]["output"] == "Target"
    # and panproto accepts it
    theory = build_theory(Holder)
    assert theory.op_count == 2
