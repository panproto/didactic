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
    with pytest.raises(ValueError, match="missing discriminator field 'kind'"):
        t.decode('{"value": 1.5}')


def test_tagged_union_decode_rejects_unknown_discriminator_value() -> None:
    from didactic.types._types import classify

    t = classify(Parameter)
    with pytest.raises(ValueError, match="no variant registered for kind="):
        t.decode('{"kind": "nonexistent", "value": 1.5}')


def test_unknown_discriminator_reaches_the_caller_as_a_validation_error() -> None:
    """``model_validate_json`` reports a decoder refusal like any other failure."""
    from didactic.fields._validators import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        _Effect.model_validate_json('{"param": {"kind": "nonexistent"}}')
    (entry,) = excinfo.value.entries
    assert entry.loc == ("param",)
    assert "no variant registered for kind='nonexistent'" in entry.msg


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


def test_no_operation_outputs_a_sort_that_closes_against_others() -> None:
    """The property panproto's ``typecheck_theory`` enforces, pinned locally.

    A closed sort's constructor list is the complete set of ways to
    build an inhabitant, so no operation outside it may output that
    sort. A union-typed field emits an accessor that does, which is why
    the sum sort is ``Open`` and its arms travel in ``constructors``.
    Asserting it here means a future change that reintroduces a
    ``Closed`` closure fails without needing panproto in the loop.
    """
    from didactic.theory._theory import build_theory_spec

    for model in (_Effect, _Track, _Chain):
        spec = build_theory_spec(model)
        closures = {
            cast("str", s["name"]): s["closure"]
            for s in spec["sorts"]
            if isinstance(s["closure"], dict)
        }
        for op in spec["ops"]:
            output = cast("str", op["output"])
            closed = closures.get(output)
            if closed is None:
                continue
            listed = cast("dict[str, list[str]]", closed)["Closed"]
            assert cast("str", op["name"]) in listed, (
                f"{model.__name__}: op {op['name']!r} outputs closed sort "
                f"{output!r} without being one of its constructors"
            )


def test_tagged_union_emits_sum_sort_in_parent_theory() -> None:
    """Theory spec for a Model with a TaggedUnion field has the sum sort."""
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(_Effect)
    sorts_by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    assert "Parameter" in sorts_by_name
    union_sort = sorts_by_name["Parameter"]
    assert union_sort["kind"] == "Structural"
    # Open, because a union-typed field emits an accessor that outputs
    # this sort; see _sum_sort_record.
    assert union_sort["closure"] == "Open"
    constructors = set(cast("list[str]", union_sort["constructors"]))
    # constructor names use the discriminator value
    assert "Parameter_constant" in constructors
    assert "Parameter_step" in constructors
