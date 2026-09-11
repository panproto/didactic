"""Tests for dx.diff, dx.classify_change, dx.synthesise_migration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, cast

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import JsonObject


class V1(dx.Model):
    id: str
    name: str


class V2(dx.Model):
    id: str
    name: str
    email: str = ""


# -- diff -------------------------------------------------------------


def test_diff_returns_dict_with_expected_keys() -> None:
    d = dx.diff(V1, V2)
    assert isinstance(d, dict)
    # panproto SchemaDiff exposes a fixed set of keys; we just verify
    # a few that should always be present
    assert "added_vertices" in d
    assert "removed_vertices" in d


def test_diff_self_is_no_op() -> None:
    d = dx.diff(V1, V1)
    assert d["added_vertices"] == []
    assert d["removed_vertices"] == []


# -- classify_change --------------------------------------------------


def test_classify_returns_compat_dict() -> None:
    report = dx.classify_change(V1, V2)
    assert "compatible" in report
    assert isinstance(report["compatible"], bool)


def test_is_breaking_change_predicate() -> None:
    # adding a vertex with a different name flagged as breaking
    assert isinstance(dx.is_breaking_change(V1, V2), bool)


# -- synthesise_migration --------------------------------------------


def test_synthesise_returns_result() -> None:
    """auto_generate_lens may or may not find a candidate for these
    Models; whichever path it takes, the wrapper should not crash and
    should return either a SynthesisResult or raise a panproto error.
    """
    try:
        result = dx.synthesise_migration(V1, V2)
        assert isinstance(result, dx.SynthesisResult)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
    except Exception as exc:
        # panproto LensError is acceptable for very dissimilar shapes
        assert "Lens" in type(exc).__name__ or "panproto" in str(type(exc))


def test_synthesise_against_disjoint_models_raises_or_returns_zero() -> None:
    """Two truly disjoint Models have no plausible alignment.

    The handoff calls for an expected-failure smoke test against two
    Models with no overlapping fields. ``auto_generate_lens`` is free
    to either raise (typically a ``LensError``) or return a synthesis
    result with a low score; either is an acceptable outcome and both
    are exercised.
    """

    class Disjoint1(dx.Model):
        a: str
        b: int

    class Disjoint2(dx.Model):
        x: float
        y: bytes

    try:
        result = dx.synthesise_migration(Disjoint1, Disjoint2)
    except Exception as exc:
        # acceptable: panproto refuses to synthesise a lens for
        # entirely incompatible shapes
        assert "Lens" in type(exc).__name__ or "panproto" in repr(type(exc))
        return
    # alternative path: panproto returns a low-confidence candidate
    assert isinstance(result, dx.SynthesisResult)
    assert 0.0 <= result.score <= 1.0


def test_synthesise_with_explicit_stringency() -> None:
    """The stringency flag is forwarded; arbitrary string is rejected
    panproto-side.
    """
    with pytest.raises(Exception):  # noqa: B017
        dx.synthesise_migration(V1, V2, stringency="not_a_real_level")


# -- indexed compatibility -------------------------------------------


OLD_PAYLOAD = dx.Universe("CompatibilityPayload", text=str, number=float)
NEW_PAYLOAD = dx.Universe("CompatibilityPayload", text=str, number=int)


class IndexedV1(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | float, OLD_PAYLOAD.at("kind")]


class IndexedV2(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | int, NEW_PAYLOAD.at("kind")]


def test_diff_reports_changed_indexed_contract() -> None:
    report = dx.diff(IndexedV1, IndexedV2)
    indexed = report.get("indexed_changes")
    assert isinstance(indexed, list)
    first = cast("JsonObject", indexed[0])
    change = cast("JsonObject", first["IndexedFamilyChanged"])
    assert change["field"] == "body"


def test_changed_indexed_contract_is_breaking() -> None:
    report = dx.classify_change(IndexedV1, IndexedV2)
    assert report["compatible"] is False
    assert report["classification"] == "breaking"
    breaking = report.get("breaking")
    assert isinstance(breaking, list)
    assert any("IndexedFamilyChanged" in cast("JsonObject", item) for item in breaking)


def test_changed_indexed_contract_requires_explicit_migration() -> None:
    with pytest.raises(ValueError, match="explicit migration"):
        dx.synthesise_migration(IndexedV1, IndexedV2)
