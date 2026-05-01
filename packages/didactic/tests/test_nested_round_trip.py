"""Regression tests for JSON round-trip across nested Embed / sum sorts.

Two bug families covered:

1. Encoder side (``model_dump_json``): a sum-sort field whose variant
   carries a ``tuple[Embed[Model], ...]`` or ``dict[str, Embed[Model]]``
   sub-field used to drop the raw nested ``Model`` instances into the
   JSON-encoded output, where ``json.dumps`` then refused to serialise
   them. The encoder now routes the variant through its own
   ``model_dump_json`` so the JSON-safe walk runs.

2. Decoder side (``model_validate_json``): an ``Embed[Inner]`` field
   round-tripped to and from JSON failed when ``Inner`` had a
   ``tuple[T, ...]`` sub-field, because the embed translation called
   ``Inner.model_validate`` on the JSON-decoded ``dict``: that bypasses
   the per-field ``from_json`` coercion that would convert the inner
   list back to a tuple. The embed translation now routes inner
   payloads through ``model_validate_json`` so per-field coercion
   runs at every level.

Both families had multiple manifestations across the bare / dict-value
/ tuple-element / Embed-wrapped placements of the outer field; this
file exercises each combination so a future regression in any one
encoder or decoder lights the suite up.
"""

from typing import Literal, cast

import didactic.api as dx
from didactic.api import embed_schema_uri


class Anchor(dx.Model):
    unit: str
    pos: float


class StepEntry(dx.Model):
    """An embedded sub-Model. Has a single ``Embed[Anchor]`` field."""

    anchor: dx.Embed[Anchor]
    value: float


class StepEntryWithTuple(dx.Model):
    """An embedded sub-Model whose own field is a ``tuple[Embed[Anchor], ...]``."""

    name: str
    anchors: tuple[dx.Embed[Anchor], ...] = ()


class StepEntryWithDict(dx.Model):
    """An embedded sub-Model whose own field is a ``dict[str, Embed[Anchor]]``."""

    name: str
    anchors: dict[str, dx.Embed[Anchor]] = dx.field(
        default_factory=lambda: cast("dict[str, dx.Embed[Anchor]]", {})
    )


class P(dx.TaggedUnion, discriminator="kind"):
    """TaggedUnion root for the encoder-side regression set."""


class StepFunction(P):
    """Variant carrying a ``tuple[Embed[StepEntry], ...]``."""

    kind: Literal["step"]
    entries: tuple[dx.Embed[StepEntry], ...] = ()


class MapFunction(P):
    """Variant carrying a ``dict[str, Embed[StepEntry]]``."""

    kind: Literal["map"]
    by_name: dict[str, dx.Embed[StepEntry]] = dx.field(
        default_factory=lambda: cast("dict[str, dx.Embed[StepEntry]]", {})
    )


def _step_function() -> StepFunction:
    return StepFunction(
        kind="step",
        entries=(StepEntry(anchor=Anchor(unit="bar", pos=0.0), value=1.0),),
    )


def _map_function() -> MapFunction:
    return MapFunction(
        kind="map",
        by_name={"x": StepEntry(anchor=Anchor(unit="bar", pos=0.5), value=2.0)},
    )


# -- (1) dict-value of TaggedUnion: variant has tuple[Embed[Model]] --------


class TrackByDictTuple(dx.Model):
    parameters: dict[str, P] = dx.field(
        default_factory=lambda: cast("dict[str, P]", {})
    )


def test_dict_of_tagged_union_with_tuple_embed_variant_round_trips() -> None:
    track = TrackByDictTuple(parameters={"tempo": _step_function()})
    js = track.model_dump_json()
    back = TrackByDictTuple.model_validate_json(js)
    assert back == track


# -- (2) dict-value of TaggedUnion: variant has dict[str, Embed[Model]] ----


def test_dict_of_tagged_union_with_dict_embed_variant_round_trips() -> None:
    track = TrackByDictTuple(parameters={"envelope": _map_function()})
    js = track.model_dump_json()
    back = TrackByDictTuple.model_validate_json(js)
    assert back == track


# -- (3) tuple-of-TaggedUnion: variant has tuple[Embed[Model]] -------------


class TrackByTupleField(dx.Model):
    chain: tuple[P, ...] = ()


def test_tuple_of_tagged_union_with_tuple_embed_variant_round_trips() -> None:
    track = TrackByTupleField(chain=(_step_function(), _map_function()))
    js = track.model_dump_json()
    back = TrackByTupleField.model_validate_json(js)
    assert back == track


# -- (4) bare TaggedUnion field: variant has tuple[Embed[Model]] -----------


class TrackByBareField(dx.Model):
    p: P


def test_bare_tagged_union_field_with_tuple_embed_variant_round_trips() -> None:
    track = TrackByBareField(p=_step_function())
    js = track.model_dump_json()
    back = TrackByBareField.model_validate_json(js)
    assert back == track


# -- (5) recursive Model-ref alias: Model arm has tuple[Embed[Model]] ------

type _Comp = (
    str
    | int
    | StepEntryWithTuple
    | list["_Comp"]
    | tuple["_Comp", ...]
    | dict[str, "_Comp"]
)


class DocWithAlias(dx.Model):
    body: _Comp


def test_alias_model_arm_with_tuple_embed_round_trips() -> None:
    step = StepEntryWithTuple(
        name="x", anchors=(Anchor(unit="bar", pos=1.0), Anchor(unit="bar", pos=2.0))
    )
    doc = DocWithAlias(body=step)
    js = doc.model_dump_json()
    back = DocWithAlias.model_validate_json(js)
    assert back == doc


def test_alias_list_arm_carrying_models_with_tuple_embed_round_trips() -> None:
    step = StepEntryWithTuple(name="x", anchors=(Anchor(unit="bar", pos=1.0),))
    doc = DocWithAlias(body=[step, step])
    back = DocWithAlias.model_validate_json(doc.model_dump_json())
    assert back == doc


type _Comp2 = str | int | StepEntryWithDict | dict[str, "_Comp2"] | tuple["_Comp2", ...]


class _Doc2(dx.Model):
    body: _Comp2


def test_alias_dict_arm_carrying_models_with_dict_embed_round_trips() -> None:
    step = StepEntryWithDict(name="x", anchors={"k": Anchor(unit="bar", pos=1.0)})
    doc = _Doc2(body={"a": step})
    back = _Doc2.model_validate_json(doc.model_dump_json())
    assert back == doc


# -- (6) embed_schema_uri on a Model with tuple[Embed[Model]] --------------


class OuterWithTupleEmbed(dx.Model):
    items: tuple[dx.Embed[StepEntry], ...] = ()


def test_embed_schema_uri_walks_into_tuple_embed_fields() -> None:
    """``embed_schema_uri`` returns a JSON-safe dict for any Model.

    Previously it called ``instance.model_dump()`` and dropped the raw
    Models; ``json.dumps`` of the result raised ``TypeError``.
    """
    import json

    outer = OuterWithTupleEmbed(
        items=(StepEntry(anchor=Anchor(unit="bar", pos=0.0), value=1.0),)
    )
    payload = embed_schema_uri(outer)
    encoded = json.dumps(payload)
    assert "items" in encoded
    assert "anchor" in encoded
    schema_uri = cast("str", payload["$schema"])
    assert schema_uri.startswith("didactic://")


# -- (7) Embed[Inner] where Inner has tuple[T, ...] ------------------------


class InnerWithTuple(dx.Model):
    items: tuple[int, ...] = ()


class OuterEmbeddingInnerWithTuple(dx.Model):
    inner: dx.Embed[InnerWithTuple]


def test_embed_inner_with_tuple_field_round_trips_via_json() -> None:
    """The outer / inner JSON round-trip preserves the tuple shape.

    Previously ``Outer.model_validate_json`` reached
    ``InnerWithTuple.model_validate(dict_payload)`` which fed the
    JSON-decoded list straight to the tuple encoder's
    ``isinstance(v, tuple)`` assertion.
    """
    o = OuterEmbeddingInnerWithTuple(inner=InnerWithTuple(items=(1, 2, 3)))
    js = o.model_dump_json()
    back = OuterEmbeddingInnerWithTuple.model_validate_json(js)
    assert back == o
    assert back.inner.items == (1, 2, 3)


def test_doubly_nested_embed_with_tuple_field_round_trips() -> None:
    """Two levels of Embed; the deepest has the tuple field."""

    class Mid(dx.Model):
        inner: dx.Embed[InnerWithTuple]

    class Outer2(dx.Model):
        mid: dx.Embed[Mid]

    o = Outer2(mid=Mid(inner=InnerWithTuple(items=(7, 8))))
    back = Outer2.model_validate_json(o.model_dump_json())
    assert back == o


def test_tuple_of_embed_inner_with_tuple_field_round_trips() -> None:
    """``tuple[Embed[Inner], ...]`` where each Inner has a tuple field.

    Stresses the same bug at the top-level container (instead of a
    bare Embed): each Inner instance has to be JSON-coerced through
    its own per-field ``from_json``.
    """

    class Holder(dx.Model):
        items: tuple[dx.Embed[InnerWithTuple], ...] = ()

    h = Holder(items=(InnerWithTuple(items=(1, 2)), InnerWithTuple(items=(3,))))
    back = Holder.model_validate_json(h.model_dump_json())
    assert back == h


# -- (8) coverage that the existing happy paths still work -----------------


class _Bare(dx.Model):
    """Sanity check that flat (non-nested) tuple round-trip still works."""

    pitches: tuple[int, ...] = ()


def test_flat_tuple_field_round_trip_unchanged() -> None:
    m = _Bare(pitches=(60, 64))
    back = _Bare.model_validate_json(m.model_dump_json())
    assert back == m


type _Json = (
    str
    | int
    | float
    | bool
    | None
    | list["_Json"]
    | tuple["_Json", ...]
    | dict[str, "_Json"]
)


class _M(dx.Model):
    params: dict[str, _Json]


def test_existing_alias_round_trip_unchanged() -> None:
    """The plain JSON-fixpoint alias path still works (no Models involved)."""
    m = _M(params={"k": [1, 2, "x"], "j": {"nested": 1.5}})
    back = _M.model_validate_json(m.model_dump_json())
    assert back == m


class Q(dx.TaggedUnion, discriminator="kind"):
    pass


class A(Q):
    kind: Literal["a"]
    value: float


class _W(dx.Model):
    q: Q


def test_existing_simple_tagged_union_round_trip_unchanged() -> None:
    """The simple TaggedUnion case (no nested Embed) still works."""
    w = _W(q=A(kind="a", value=1.5))
    back = _W.model_validate_json(w.model_dump_json())
    assert isinstance(back.q, A)
    assert back.q.value == 1.5
