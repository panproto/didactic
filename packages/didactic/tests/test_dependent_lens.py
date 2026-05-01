"""Tests for ``dx.DependentLens``.

The wrapper delegates to ``panproto.ProtolensChain`` for the
substantive computation; these tests verify the didactic-side surface
(constructors, composition, JSON round-trip, instantiation).
"""

from __future__ import annotations

import pytest
import panproto

import didactic.api as dx


def _build_schema(vertex_name: str = "ping") -> panproto.Schema:
    """Build a minimal panproto schema with one vertex."""
    proto = panproto.get_builtin_protocol("openapi")
    builder = proto.schema()
    builder.vertex(vertex_name, "string")
    return builder.build()


def _proto() -> panproto.Protocol:
    return panproto.get_builtin_protocol("openapi")


# -- auto-generation ---------------------------------------------------


def test_auto_generate_returns_dependent_lens() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    assert isinstance(chain, dx.DependentLens)


def test_auto_generate_repr_contains_class_name() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    assert "DependentLens(" in repr(chain)


# -- json round-trip ---------------------------------------------------


def test_to_json_returns_string() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    js = chain.to_json()
    assert isinstance(js, str)


def test_from_json_round_trips() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    js = chain.to_json()
    rebuilt = dx.DependentLens.from_json(js)
    assert rebuilt == chain
    assert hash(rebuilt) == hash(chain)


def test_from_json_rejects_garbage() -> None:
    with pytest.raises(panproto.LensError):
        dx.DependentLens.from_json("not a serialised chain")


# -- composition -------------------------------------------------------


def test_compose_returns_dependent_lens() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    a = dx.DependentLens.auto_generate(src, tgt, _proto())
    b = dx.DependentLens.auto_generate(tgt, src, _proto())
    composed = a.compose(b)
    assert isinstance(composed, dx.DependentLens)


def test_rshift_is_compose() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    a = dx.DependentLens.auto_generate(src, tgt, _proto())
    b = dx.DependentLens.auto_generate(tgt, src, _proto())
    via_compose = a.compose(b)
    via_rshift = a >> b
    assert via_compose == via_rshift


# -- instantiation -----------------------------------------------------


def test_instantiate_against_concrete_schema() -> None:
    """Instantiate a chain against a matching schema."""
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    concrete = chain.instantiate(src, _proto())
    # the concrete result is a panproto.Lens; we don't assert on its
    # internal shape, just that it round-trips through panproto without
    # raising
    assert concrete is not None


# -- equality ---------------------------------------------------------


def test_equal_chains_compare_equal() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain_a = dx.DependentLens.auto_generate(src, tgt, _proto())
    chain_b = dx.DependentLens.from_json(chain_a.to_json())
    assert chain_a == chain_b


def test_inequality_with_non_dependent_lens() -> None:
    src = _build_schema("a")
    tgt = _build_schema("a")
    chain = dx.DependentLens.auto_generate(src, tgt, _proto())
    assert chain != "not a chain"
    assert chain != 42
