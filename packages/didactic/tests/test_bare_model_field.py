"""``tuple[Model, ...]`` and bare-Model fields without explicit ``Embed``.

A ``dx.Model`` subclass used directly as a field type classifies
through the same Embed-shaped translation that ``Embed[T]`` would
have produced; the wire format and runtime semantics are identical.
"""

from __future__ import annotations

from typing import cast

import didactic.api as dx


class _Operation(dx.Model):
    name: str
    arity: int = 0


class _EffectSignature(dx.Model):
    operations: tuple[_Operation, ...] = ()


class _Container(dx.Model):
    """Mix bare-Model fields with the existing Embed/scalar shapes."""

    head: _Operation
    body: tuple[_Operation, ...] = ()
    by_name: dict[str, _Operation] = dx.field(
        default_factory=lambda: cast("dict[str, _Operation]", {})
    )


def test_tuple_of_bare_model_constructs() -> None:
    s = _EffectSignature(
        operations=(_Operation(name="a"), _Operation(name="b", arity=2))
    )
    assert len(s.operations) == 2
    assert s.operations[0].name == "a"
    assert s.operations[1].arity == 2


def test_tuple_of_bare_model_round_trips_json() -> None:
    s = _EffectSignature(
        operations=(_Operation(name="a"), _Operation(name="b", arity=2))
    )
    out = _EffectSignature.model_validate_json(s.model_dump_json())
    assert out == s
    assert isinstance(out.operations[0], _Operation)


def test_bare_model_scalar_field_works() -> None:
    """``head: _Operation`` (no container) routes through Embed too."""
    c = _Container(head=_Operation(name="x"))
    assert isinstance(c.head, _Operation)
    rt = _Container.model_validate_json(c.model_dump_json())
    assert rt.head.name == "x"


def test_dict_of_bare_model_round_trips() -> None:
    c = _Container(
        head=_Operation(name="root"),
        by_name={"a": _Operation(name="a"), "b": _Operation(name="b")},
    )
    rt = _Container.model_validate_json(c.model_dump_json())
    assert set(rt.by_name) == {"a", "b"}
    assert isinstance(rt.by_name["a"], _Operation)


def test_bare_model_dict_input_dispatches_through_construction() -> None:
    """Construction with a dict child runs the embed encoder's coercion path."""
    s = _EffectSignature(
        operations=({"name": "lit", "arity": 1},)  # type: ignore[arg-type]
    )
    assert isinstance(s.operations[0], _Operation)
    assert s.operations[0].name == "lit"
