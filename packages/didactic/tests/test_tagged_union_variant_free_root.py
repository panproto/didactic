"""A ``dx.TaggedUnion`` root with no variants yet is a usable field type.

The variant registry is written by each variant's own class body, so a
root declared in a module that must not import its variants has an
empty registry until something else imports them. Field classification
therefore does not consult the registry, and the auxiliary sum sort is
recomputed when the Theory is built rather than frozen at classify
time.

This file deliberately omits ``from __future__ import annotations``:
see the note at the top of ``test_tagged_union_field.py``.
"""

from typing import Literal, cast

import pytest

import didactic.api as dx
from didactic.fields._validators import ValidationError
from didactic.theory._theory import build_theory_spec
from didactic.types._types import classify


class ParserSpec(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """A parser, chosen by tag. Its variants are declared further down."""


class RunSpec(dx.Model):
    """Declared while ``ParserSpec.__variants__`` is still empty."""

    parser: ParserSpec
    fallback: ParserSpec | None = None
    stages: tuple[ParserSpec, ...] = ()
    by_name: dict[str, ParserSpec] = {}


class ChartParser(ParserSpec):
    """Registered strictly after ``RunSpec`` classified its fields."""

    kind: Literal["chart"] = "chart"
    beam: int = 8


class _Empty(dx.TaggedUnion, discriminator="kind"):
    """A root that stays variant-free for the whole module."""


class _HoldsEmpty(dx.Model):
    node: _Empty


def test_variant_free_root_classifies() -> None:
    """``classify`` accepts the root itself, not just a populated one."""
    t = classify(_Empty)
    assert t.inner_kind == "sum"
    assert t.sort == "_Empty"


def test_variant_free_root_is_usable_in_every_container_spelling() -> None:
    """The bare, optional, tuple and dict spellings all build a field spec."""
    assert set(RunSpec.__field_specs__) == {
        "parser",
        "fallback",
        "stages",
        "by_name",
    }
    assert _HoldsEmpty.__field_specs__["node"].translation.inner_kind == "sum"


def test_late_variant_round_trips_through_the_field() -> None:
    """A variant registered after classify encodes and decodes."""
    run = RunSpec(parser=ChartParser(beam=4))
    restored = RunSpec.model_validate_json(run.model_dump_json())
    assert isinstance(restored.parser, ChartParser)
    assert restored.parser.beam == 4


def test_late_variant_round_trips_through_every_container_spelling() -> None:
    """Optional, tuple and dict fields over the root round-trip too."""
    run = RunSpec(
        parser=ChartParser(beam=1),
        fallback=ChartParser(beam=2),
        stages=(ChartParser(beam=3),),
        by_name={"main": ChartParser(beam=4)},
    )
    restored = RunSpec.model_validate_json(run.model_dump_json())
    assert restored.fallback == ChartParser(beam=2)
    assert restored.stages == (ChartParser(beam=3),)
    assert restored.by_name == {"main": ChartParser(beam=4)}


def test_late_variant_dispatches_from_a_dict_payload() -> None:
    """A dict carrying the discriminator resolves through the live registry.

    The field is typed as the union root, so the dict spelling needs the
    same ``type: ignore`` the other dict-payload tests carry.
    """
    run = RunSpec(parser={"kind": "chart", "beam": 2})  # type: ignore[arg-type]
    assert isinstance(run.parser, ChartParser)
    assert run.parser.beam == 2


def test_second_variant_registered_later_still_participates() -> None:
    """Registration keeps working after the first variant is in place."""

    class _Later(ParserSpec):
        kind: Literal["later"] = "later"
        depth: int = 1

    run = RunSpec(parser=_Later(depth=3))
    restored = RunSpec.model_validate_json(run.model_dump_json())
    assert isinstance(restored.parser, _Later)
    assert restored.parser.depth == 3
    del ParserSpec.__variants__["later"]


def test_unknown_discriminator_is_refused() -> None:
    """An unregistered tag fails validation rather than dispatching."""
    with pytest.raises(ValidationError, match="no variant registered for kind="):
        RunSpec.model_validate_json('{"parser": {"kind": "nope"}}')


def test_theory_sum_sort_names_the_variants_registered_by_build_time() -> None:
    """The auxiliary sum sort is recomputed from the live registry."""
    spec = build_theory_spec(RunSpec)
    sorts_by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    closure = cast("dict[str, list[str]]", sorts_by_name["ParserSpec"]["closure"])
    assert closure["Closed"] == ["ParserSpec_chart"]
    op_names = {cast("str", op["name"]) for op in spec["ops"]}
    assert "ParserSpec_chart" in op_names


def test_theory_sum_sort_is_empty_while_the_root_has_no_variants() -> None:
    """A root with nothing registered contributes a closed sum over no tags."""
    spec = build_theory_spec(_HoldsEmpty)
    sorts_by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    closure = cast("dict[str, list[str]]", sorts_by_name["_Empty"]["closure"])
    assert closure["Closed"] == []
    assert _HoldsEmpty.__theory__ is not None


def test_resolve_auxiliary_tracks_registrations_made_after_classify() -> None:
    """The provider is consulted per call, so a later variant shows up."""

    class _Root(dx.TaggedUnion, discriminator="kind"):
        pass

    translation = classify(_Root)
    sorts, ops = translation.resolve_auxiliary()
    assert cast("dict[str, list[str]]", sorts[0]["closure"])["Closed"] == []
    assert ops == ()

    class _Arm(_Root):
        kind: Literal["arm"] = "arm"

    assert _Root.__variants__["arm"] is _Arm
    sorts, ops = translation.resolve_auxiliary()
    assert cast("dict[str, list[str]]", sorts[0]["closure"])["Closed"] == ["_Root_arm"]
    assert [cast("str", op["name"]) for op in ops] == ["_Root_arm"]


def test_union_of_roots_accepts_a_variant_free_arm() -> None:
    """``A | B`` classifies even when one arm has nothing registered yet."""

    class _LeftRoot(dx.TaggedUnion, discriminator="kind"):
        pass

    class _RightRoot(dx.TaggedUnion, discriminator="kind"):
        pass

    class _Pair(dx.Model):
        item: _LeftRoot | _RightRoot | None = None

    class _LeftArm(_LeftRoot):
        kind: Literal["left"] = "left"
        n: int = 0

    pair = _Pair(item=_LeftArm(n=7))
    restored = _Pair.model_validate_json(pair.model_dump_json())
    assert isinstance(restored.item, _LeftArm)
    assert restored.item.n == 7
