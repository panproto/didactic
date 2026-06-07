"""Tests for ``dx.find_correspondences`` / ``dx.best_correspondence``.

The wrappers delegate to ``panproto.find_morphisms`` /
``panproto.find_best_morphism``; these tests verify the didactic-side
surface (record shape, ordering, constraint pass-through) and the
discover-then-derive pipeline into
``DependentLens.auto_generate_with_hints``.
"""

from __future__ import annotations

import panproto

import didactic.api as dx


def _proto() -> panproto.Protocol:
    return panproto.get_builtin_protocol("atproto")


def _post_schema(body_field: str) -> panproto.Schema:
    """Build a three-vertex atproto schema with one body prop."""
    builder = _proto().schema()
    builder.vertex("post", "record", "app.bsky.feed.post")
    builder.vertex("post:body", "object")
    builder.vertex(f"post:body.{body_field}", "string")
    builder.edge("post", "post:body", "record-schema")
    builder.edge("post:body", f"post:body.{body_field}", "prop", body_field)
    return builder.build()


# -- find_correspondences ----------------------------------------------


def test_find_correspondences_returns_records() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    found = dx.find_correspondences(src, tgt)
    assert found
    assert all(isinstance(c, dx.Correspondence) for c in found)


def test_find_correspondences_discovers_rename() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    found = dx.find_correspondences(src, tgt)
    maps = [c.vertex_map for c in found]
    assert {
        "post": "post",
        "post:body": "post:body",
        "post:body.text": "post:body.content",
    } in maps


def test_find_correspondences_quality_in_unit_interval() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    for c in dx.find_correspondences(src, tgt):
        assert 0.0 <= c.quality <= 1.0


def test_find_correspondences_identical_schemas_score_higher() -> None:
    same = dx.best_correspondence(_post_schema("text"), _post_schema("text"))
    renamed = dx.best_correspondence(_post_schema("text"), _post_schema("content"))
    assert same is not None
    assert renamed is not None
    assert same.quality >= renamed.quality


# -- best_correspondence -----------------------------------------------


def test_best_correspondence_matches_enumeration_maximum() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    best = dx.best_correspondence(src, tgt)
    found = dx.find_correspondences(src, tgt)
    assert best is not None
    assert best.quality == max(c.quality for c in found)


def test_best_correspondence_respects_anchors() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    best = dx.best_correspondence(src, tgt, anchors={"post": "post"})
    assert best is not None
    assert best.vertex_map["post"] == "post"


# -- pipeline into DependentLens ---------------------------------------


def test_vertex_map_feeds_auto_generate_with_hints() -> None:
    src = _post_schema("text")
    tgt = _post_schema("content")
    best = dx.best_correspondence(src, tgt)
    assert best is not None
    chain = dx.DependentLens.auto_generate_with_hints(
        src,
        tgt,
        _proto(),
        best.vertex_map,
    )
    assert isinstance(chain, dx.DependentLens)


# -- record semantics --------------------------------------------------


def test_correspondence_is_frozen() -> None:
    import dataclasses

    c = dx.Correspondence(vertex_map={"a": "b"}, quality=0.5)
    assert dataclasses.is_dataclass(c)
    try:
        c.quality = 0.9  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    msg = "Correspondence must be frozen"
    raise AssertionError(msg)
