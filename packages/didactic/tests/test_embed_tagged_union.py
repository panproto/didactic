"""``Embed[Root]`` preserves variant subclass identity.

Before the v0.5.2 fix, embedding a TaggedUnion variant inside another
Model's field stored the variant's storage dict but reconstructed it
as the bare root class (which has no field specs of its own). Every
variant-specific field was invisible after a round-trip through the
Embed boundary. The fix dispatches at decode time on the stored
discriminator value.
"""

from __future__ import annotations

from typing import Literal

import pytest

import didactic.api as dx


class _Node(dx.TaggedUnion, discriminator="kind"):
    pass


class _Lit(_Node):
    kind: Literal["lit"]
    value: int


class _Var(_Node):
    kind: Literal["var"]
    name: str


class _Container(dx.Model):
    items: tuple[dx.Embed[_Node], ...] = ()
    head: dx.Embed[_Node] | None = None


class _Inner(dx.Model):
    x: int


class _Outer(dx.Model):
    inner: dx.Embed[_Inner]


# Variant declared late (after Container's Embed-typed field was classified)
# to pin the live-registry path through the Embed encoder/decoder.
class _LateLit(_Node):
    kind: Literal["late"]
    value: float = 0.0


def test_embed_tagged_union_preserves_variant_identity_in_tuple() -> None:
    c = _Container(
        items=(
            _Lit(kind="lit", value=1),
            _Var(kind="var", name="x"),
            _Lit(kind="lit", value=99),
        )
    )
    types = [type(item).__name__ for item in c.items]
    assert types == ["_Lit", "_Var", "_Lit"]
    # The variant's own field is reachable on the recovered instance.
    assert c.items[0].value == 1  # type: ignore[union-attr]
    assert c.items[1].name == "x"  # type: ignore[union-attr]


def test_embed_tagged_union_round_trips_through_json() -> None:
    c = _Container(
        items=(_Lit(kind="lit", value=7), _Var(kind="var", name="y")),
    )
    out = _Container.model_validate_json(c.model_dump_json())
    types = [type(item).__name__ for item in out.items]
    assert types == ["_Lit", "_Var"]
    assert out.items[0].value == 7  # type: ignore[union-attr]
    assert out.items[1].name == "y"  # type: ignore[union-attr]


def test_embed_tagged_union_scalar_field_round_trip() -> None:
    """Single (non-container) ``Embed[Root]`` field carries the variant too."""
    c = _Container(head=_Var(kind="var", name="alpha"))
    assert isinstance(c.head, _Var)
    assert c.head.name == "alpha"
    out = _Container.model_validate_json(c.model_dump_json())
    assert isinstance(out.head, _Var)
    assert out.head.name == "alpha"


def test_embed_tagged_union_storage_round_trip() -> None:
    """``from_storage_dict`` (the pickle path) round-trips variants too."""
    c = _Container(items=(_Lit(kind="lit", value=42),))
    storage = c.to_storage_dict()
    recovered = _Container.from_storage_dict(storage)
    assert isinstance(recovered.items[0], _Lit)
    assert recovered.items[0].value == 42


def test_embed_tagged_union_late_registered_variant_round_trips() -> None:
    """Variants defined after the Embed-typed field's classify call work.

    ``_LateLit`` is declared at module scope after ``_Container``; the
    Embed encoder must therefore consult ``_Node.__variants__`` live
    on every encode/decode call (the same pattern as #24's fix).
    """
    c = _Container(items=(_LateLit(kind="late", value=2.5),))
    out = _Container.model_validate_json(c.model_dump_json())
    assert isinstance(out.items[0], _LateLit)
    assert out.items[0].value == 2.5  # type: ignore[union-attr]


def test_embed_non_tagged_union_unaffected() -> None:
    """Plain ``Embed[T]`` (no TaggedUnion) keeps the legacy behaviour."""
    o = _Outer(inner=_Inner(x=5))
    out = _Outer.model_validate_json(o.model_dump_json())
    assert isinstance(out.inner, _Inner)
    assert out.inner.x == 5


def test_embed_tagged_union_unknown_discriminator_falls_back_to_root() -> None:
    """A storage entry with an unregistered discriminator value decodes as the root.

    Stale storage from a schema older than the current variant set
    must not crash decoding; falling back to the root preserves what
    we can. The variant-specific fields will not be reachable, but
    the construction succeeds.
    """
    storage_w_bad_disc = {
        "items": '["{\\"kind\\": \\"unregistered\\", \\"value\\": 1}"]',
        "head": "null",
    }
    recovered = _Container.from_storage_dict(storage_w_bad_disc)
    assert isinstance(recovered.items[0], _Node)
    assert not isinstance(recovered.items[0], (_Lit, _Var))


# Regression for the issue's exact repro.


def test_issue_27_repro_module_scope() -> None:
    """The exact repro from issue #27 against the module-scope classes.

    Function-scope class definitions can't be used here because the
    test module sets ``from __future__ import annotations``, so a
    function-local class annotation like ``items: tuple[Embed[N], ...]``
    becomes a ``ForwardRef`` that can't resolve outside the function.
    The module-level ``_Container`` and ``_Lit`` cover the same shape.
    """
    w = _Container(items=(_Lit(kind="lit", value=1),))
    assert type(w.items[0]).__name__ == "_Lit"
    assert w.items[0].value == 1  # type: ignore[union-attr]


def test_dict_input_is_dispatched_to_correct_variant() -> None:
    """Construction with a dict child also resolves to the correct variant."""
    c = _Container(
        items=({"kind": "lit", "value": 11},),  # type: ignore[arg-type]
    )
    assert isinstance(c.items[0], _Lit)
    assert c.items[0].value == 11


def test_passing_wrong_type_still_errors() -> None:
    """The dispatch fix doesn't loosen the input type check."""
    with pytest.raises(dx.ValidationError):
        _Container(items=(42,))  # type: ignore[arg-type]
