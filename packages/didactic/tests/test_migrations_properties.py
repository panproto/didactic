"""Property-based tests for the migration registry.

These tests use Hypothesis to generate random pairs of structurally
identical Model class definitions, then confirm that:

- Two structurally identical Models hash to the same structural
  fingerprint, regardless of class name.
- A migration registered against one pair is found by ``migrate`` when
  called against the other pair (the fingerprint-equivalence guarantee).
- ``migrate(payload, source=A, target=A)`` is a no-op for any Model.
"""

from __future__ import annotations

import string
import types
from typing import Protocol, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import didactic.api as dx
from didactic.migrations._fingerprint import structural_fingerprint
from didactic.migrations._migrations import clear_registry
from didactic.theory._theory import build_theory_spec


@pytest.fixture(autouse=True)
def isolated_registry() -> None:
    """Clear the migration registry before each test."""
    clear_registry()


# Hypothesis strategy for valid Python identifiers
_letters = string.ascii_letters


def _join_ident(head: str, tail: str) -> str:
    return head + tail


_idents: st.SearchStrategy[str] = st.builds(
    _join_ident,
    st.sampled_from(_letters),
    st.text(alphabet=_letters + string.digits + "_", min_size=0, max_size=8),
)


def _build_model_class(class_name: str, annotations: dict[str, type]) -> type[dx.Model]:
    """Build a Model subclass with the given name and field annotations.

    Uses ``types.new_class`` so the metaclass (``ModelMeta``) is invoked
    via the standard class-creation machinery; the resulting object is a
    ``dx.Model`` subclass at runtime.
    """
    cls = types.new_class(
        class_name,
        (dx.Model,),
        exec_body=lambda ns: ns.update({"__annotations__": annotations}),
    )
    return cast("type[dx.Model]", cls)


def _make_user_class(class_name: str) -> type[dx.Model]:
    """Build a ``class {class_name}(dx.Model): id: str; name: str``."""
    return _build_model_class(class_name, {"id": str, "name": str})


# -- structural fingerprint properties ---------------------------------


@given(_idents, _idents)
@settings(max_examples=50)
def test_structurally_identical_classes_share_fingerprint(
    name_a: str, name_b: str
) -> None:
    """Two Models with the same fields hash to the same structural fingerprint."""
    cls_a = _make_user_class(f"A_{name_a}")
    cls_b = _make_user_class(f"B_{name_b}")

    fp_a = structural_fingerprint(build_theory_spec(cls_a))
    fp_b = structural_fingerprint(build_theory_spec(cls_b))

    assert fp_a == fp_b


@given(_idents)
@settings(max_examples=20)
def test_structural_fingerprint_is_deterministic(name: str) -> None:
    """Building a fingerprint twice for the same spec yields the same hex."""
    cls = _make_user_class(f"X_{name}")
    spec = build_theory_spec(cls)
    assert structural_fingerprint(spec) == structural_fingerprint(spec)


# -- migrate identity property -----------------------------------------


@given(st.text(max_size=20), st.text(max_size=20))
@settings(max_examples=50)
def test_migrate_to_same_class_is_identity(uid: str, name: str) -> None:
    class User(dx.Model):
        id: str
        name: str

    u = User(id=uid, name=name)
    out = dx.migrate(u, target=User)
    assert out is u


# -- registry lookup property ------------------------------------------


@given(_idents, _idents)
@settings(max_examples=20, deadline=None)
def test_register_one_pair_finds_lookup_under_structurally_equivalent_pair(
    suffix_a: str,
    suffix_b: str,
) -> None:
    """Register A1->A2; lookup B1->B2 (same shape, fresh names) finds the lens."""
    # hypothesis re-enters the test body for each example, so a single
    # autouse fixture isn't enough; clear before each example
    clear_registry()
    # ensure unique class names per Hypothesis example so we don't collide
    name_a1 = f"OrigOne_{suffix_a}"
    name_a2 = f"OrigTwo_{suffix_a}"
    name_b1 = f"FreshOne_{suffix_b}"
    name_b2 = f"FreshTwo_{suffix_b}"

    # source class: id+name; target class: id+given_name
    a1 = _build_model_class(name_a1, {"id": str, "name": str})
    a2 = _build_model_class(name_a2, {"id": str, "given_name": str})

    class _IdName(Protocol):
        id: str
        name: str

    class _IdGiven(Protocol):
        id: str
        given_name: str

    class Migration(dx.Iso[a1, a2]):  # type: ignore[valid-type, misc]
        def forward(self, a: dx.Model, /) -> dx.Model:
            x = cast("_IdName", a)
            return a2(id=x.id, given_name=x.name)

        def backward(self, b: dx.Model, /) -> dx.Model:
            x = cast("_IdGiven", b)
            return a1(id=x.id, name=x.given_name)

    dx.register_migration(a1, a2, Migration())

    b1 = _build_model_class(name_b1, {"id": str, "name": str})
    b2 = _build_model_class(name_b2, {"id": str, "given_name": str})

    from didactic.migrations._migrations import lookup_migration

    assert lookup_migration(b1, b2) is not None

    # and migrate works end-to-end
    out = dx.migrate(b1(id="u1", name="Ada"), target=b2)
    # the registered lens constructs ``a2``; structural equivalence
    # guarantees the lens is found, not that the result class is ``b2``
    assert out.id == "u1"
    assert out.given_name == "Ada"
