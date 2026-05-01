"""Tests for using ``dx.TaggedUnion`` as a field value type.

This file deliberately omits ``from __future__ import annotations``.
``TaggedUnion.__init_subclass__`` reads variant annotations via
``annotationlib.get_annotations(format=FORWARDREF)`` and rejects an
unresolved ``Literal[...]`` string; with the future-annotations import
in scope, every annotation is a string at class-creation time and the
metaclass refuses the variant. Module-level eager annotations let the
metaclass see real ``Literal`` types.
"""

from typing import Literal, cast

import pytest

import didactic.api as dx


class Parameter(dx.TaggedUnion, discriminator="kind"):
    """Sum-type root for the issue #5 motivating shape."""


class ConstantParam(Parameter):
    """A constant scalar parameter."""

    kind: Literal["constant"]
    value: float


class StepParam(Parameter):
    """A parameter that steps through a fixed sequence of levels."""

    kind: Literal["step"]
    levels: tuple[float, ...]


class _Track(dx.Model):
    parameters: dict[str, Parameter]


class _Effect(dx.Model):
    param: Parameter


class _Chain(dx.Model):
    parameters: tuple[Parameter, ...]


def test_tagged_union_classifies_as_named_sort() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    assert t.sort == "Parameter"
    assert t.inner_kind == "sum"


def test_tagged_union_round_trips_a_variant() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    c = ConstantParam(kind="constant", value=3.14)
    decoded = t.decode(t.encode(c))
    assert isinstance(decoded, ConstantParam)
    assert decoded == c


def test_tagged_union_decode_dispatches_via_discriminator() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    s = StepParam(kind="step", levels=(1.0, 2.0, 3.0))
    decoded = t.decode(t.encode(s))
    assert isinstance(decoded, StepParam)
    assert decoded == s


def test_tagged_union_encode_preserves_discriminator_in_payload() -> None:
    """The wire format is the variant's natural ``model_dump`` (no envelope)."""
    import json

    from didactic.types._types import classify

    t = classify(Parameter)
    raw = json.loads(t.encode(ConstantParam(kind="constant", value=1.5)))
    assert raw == {"kind": "constant", "value": 1.5}


def test_tagged_union_decode_rejects_missing_discriminator() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    with pytest.raises(KeyError):
        t.decode('{"value": 1.5}')


def test_tagged_union_decode_rejects_unknown_discriminator_value() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    with pytest.raises(KeyError):
        t.decode('{"kind": "nonexistent", "value": 1.5}')


def test_tagged_union_works_as_dict_value_type() -> None:
    """Issue #5 motivating case: ``dict[str, Parameter]``."""
    track = _Track(
        parameters={
            "tempo": ConstantParam(kind="constant", value=120.0),
            "envelope": StepParam(kind="step", levels=(0.1, 0.5, 0.2)),
        }
    )
    raw = track.model_dump_json()
    track2 = _Track.model_validate_json(raw)
    assert track2.parameters["tempo"] == ConstantParam(kind="constant", value=120.0)
    assert track2.parameters["envelope"] == StepParam(
        kind="step", levels=(0.1, 0.5, 0.2)
    )


def test_tagged_union_works_as_bare_field_type() -> None:
    """Issue #5: ``param: Parameter`` directly."""
    e = _Effect(param=ConstantParam(kind="constant", value=0.7))
    e2 = _Effect.model_validate_json(e.model_dump_json())
    assert isinstance(e2.param, ConstantParam)
    assert e2.param.value == 0.7


def test_tagged_union_works_as_tuple_element() -> None:
    """Issue #5: ``parameters: tuple[Parameter, ...]``."""
    c = _Chain(
        parameters=(
            ConstantParam(kind="constant", value=1.0),
            StepParam(kind="step", levels=(0.0, 0.5, 1.0)),
        )
    )
    c2 = _Chain.model_validate_json(c.model_dump_json())
    assert c2.parameters == c.parameters


def test_tagged_union_emits_closed_sum_sort_in_parent_theory() -> None:
    """Theory spec for a Model with a TaggedUnion field has the closed sum sort."""
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_Effect)
    sorts_by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    assert "Parameter" in sorts_by_name
    union_sort = sorts_by_name["Parameter"]
    assert union_sort["kind"] == "Structural"
    closure = cast("dict[str, list[str]]", union_sort["closure"])
    constructors = set(closure["Closed"])
    # constructor names use the discriminator value
    assert "Parameter_constant" in constructors
    assert "Parameter_step" in constructors
