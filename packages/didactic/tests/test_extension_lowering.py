from __future__ import annotations

from dataclasses import dataclass

import pytest

from didactic.extensions import (
    LoweringRoute,
    UnsupportedLoweringRouteError,
    lower_checked,
    supports_lowering,
)


@dataclass(frozen=True, slots=True)
class _Source:
    stable_id: str
    provenance: tuple[str | int, ...]
    effects: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Checked:
    source: _Source


@dataclass(frozen=True, slots=True)
class _Target:
    stable_id: str
    provenance: tuple[str | int, ...]
    effects: tuple[str, ...]


class _Lowerer:
    route = LoweringRoute("surface/v1", "typed-core/v1alpha1")

    def __init__(self) -> None:
        self.stages: list[str] = []

    def check(self, source: _Source, /) -> _Checked:
        self.stages.append("check")
        if source.stable_id == "reject":
            raise TypeError("source check failed")
        return _Checked(source)

    def lower(self, checked: _Checked, /) -> _Target:
        self.stages.append("lower")
        source = checked.source
        return _Target(source.stable_id, source.provenance, source.effects)

    def validate(self, target: _Target, /) -> None:
        self.stages.append("validate")
        if target.stable_id == "malformed":
            raise ValueError("target validation failed")


def test_lower_checked_preserves_extension_owned_distinctions() -> None:
    source = _Source(
        "nominal:decl:42",
        ("module", "body", 3),
        ("State[Int]@left", "State[Int]@right", "rho\\left,right"),
    )
    lowerer = _Lowerer()

    target = lower_checked(
        source,
        lowerer,
        source_version="surface/v1",
        target_version="typed-core/v1alpha1",
    )

    assert target == _Target(source.stable_id, source.provenance, source.effects)
    assert lowerer.stages == ["check", "lower", "validate"]


def test_version_negotiation_fails_before_checking() -> None:
    lowerer = _Lowerer()
    source = _Source("id", (), ())

    assert supports_lowering(
        lowerer,
        source_version="surface/v1",
        target_version="typed-core/v1alpha1",
    )
    assert not supports_lowering(
        lowerer,
        source_version="surface/v2",
        target_version="typed-core/v1alpha1",
    )
    with pytest.raises(UnsupportedLoweringRouteError, match="surface/v2"):
        lower_checked(
            source,
            lowerer,
            source_version="surface/v2",
            target_version="typed-core/v1alpha1",
        )
    assert lowerer.stages == []


def test_check_and_validation_failures_stop_the_pipeline() -> None:
    rejected = _Lowerer()
    with pytest.raises(TypeError, match="source check failed"):
        lower_checked(
            _Source("reject", (), ()),
            rejected,
            source_version="surface/v1",
            target_version="typed-core/v1alpha1",
        )
    assert rejected.stages == ["check"]

    malformed = _Lowerer()
    with pytest.raises(ValueError, match="target validation failed"):
        lower_checked(
            _Source("malformed", (), ()),
            malformed,
            source_version="surface/v1",
            target_version="typed-core/v1alpha1",
        )
    assert malformed.stages == ["check", "lower", "validate"]


def test_lowering_routes_reject_empty_version_identifiers() -> None:
    with pytest.raises(ValueError, match="source version"):
        LoweringRoute("", "typed-core/v1")
    with pytest.raises(ValueError, match="target version"):
        LoweringRoute("surface/v1", "")
