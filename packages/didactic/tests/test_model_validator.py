"""``@dx.model_validator`` runs class-level checks after axioms.

Pins v0.5.3's class-level cross-field validation surface. The
decorator is the equivalent of Pydantic v2's
``@model_validator(mode="after")``.
"""

from __future__ import annotations

import pytest

import didactic.api as dx


class _Rules(dx.Model):
    binary_rules: tuple[str, ...] = ()
    binary_weights: tuple[float, ...] | None = None

    @dx.model_validator()
    def _check(self) -> _Rules:
        if self.binary_weights is not None and len(self.binary_weights) != len(
            self.binary_rules
        ):
            msg = "binary_weights length must match binary_rules length"
            raise ValueError(msg)
        return self


def test_model_validator_passes_when_invariant_holds() -> None:
    _Rules(binary_rules=("a", "b"), binary_weights=(0.5, 0.5))
    _Rules(binary_rules=("a",))  # weights None bypasses


def test_model_validator_failure_surfaces_as_validation_error() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _Rules(binary_rules=("a", "b"), binary_weights=(0.5,))
    entry = exc.value.entries[0]
    assert entry.type == "validator_error"
    assert entry.loc == ()
    assert "length" in entry.msg


def test_invalid_mode_rejected_at_decoration_time() -> None:
    with pytest.raises(ValueError, match="only accepts 'after'"):
        dx.model_validator(mode="before")


# -- inheritance -----------------------------------------------------


class _BaseRules(dx.Model):
    n: int = 0

    @dx.model_validator()
    def _nonneg(self) -> _BaseRules:
        if self.n < 0:
            msg = "n must be non-negative"
            raise ValueError(msg)
        return self


class _ChildRules(_BaseRules):
    pass


def test_subclass_inherits_model_validator() -> None:
    with pytest.raises(dx.ValidationError):
        _ChildRules(n=-1)


# -- multiple model validators run together --------------------------


class _Multi(dx.Model):
    x: int = 0
    y: int = 0

    @dx.model_validator()
    def _x_nonneg(self) -> _Multi:
        if self.x < 0:
            msg = "x must be non-negative"
            raise ValueError(msg)
        return self

    @dx.model_validator()
    def _y_le_x(self) -> _Multi:
        if self.y > self.x:
            msg = "y must not exceed x"
            raise ValueError(msg)
        return self


def test_multiple_validators_collect_all_failures() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _Multi(x=-1, y=5)
    msgs = sorted(e.msg for e in exc.value.entries)
    assert "x must be non-negative" in msgs
    assert "y must not exceed x" in msgs


# -- model_validator runs after axioms ------------------------------


class _Ordered(dx.Model):
    low: int = 0
    high: int = 10

    __axioms__ = (dx.axiom("low <= high"),)

    @dx.model_validator()
    def _diff(self) -> _Ordered:
        if (self.high - self.low) > 100:
            msg = "range too wide"
            raise ValueError(msg)
        return self


def test_axiom_failure_surfaces_before_model_validator_runs() -> None:
    """Axioms run first; if they fail, model_validator never executes.

    A ``low > high`` instance must raise an axiom failure rather than
    reach the ``_diff`` body (which would raise its own complaint).
    """
    with pytest.raises(dx.ValidationError) as exc:
        _Ordered(low=10, high=0)
    types = {e.type for e in exc.value.entries}
    assert "axiom_failed" in types
    assert "validator_error" not in types


# -- the issue's repro shape -----------------------------------------


class _RuleSystem(dx.Model):
    binary_rules: tuple[str, ...] = ()
    binary_weights: tuple[float, ...] | None = None
    unary_rules: tuple[str, ...] = ()
    unary_weights: tuple[float, ...] | None = None

    @dx.model_validator()
    def _both_lengths(self) -> _RuleSystem:
        if self.binary_weights is not None and len(self.binary_weights) != len(
            self.binary_rules
        ):
            msg = "binary length mismatch"
            raise ValueError(msg)
        if self.unary_weights is not None and len(self.unary_weights) != len(
            self.unary_rules
        ):
            msg = "unary length mismatch"
            raise ValueError(msg)
        return self


def test_quivers_rule_system_repro() -> None:
    _RuleSystem(binary_rules=("a",), binary_weights=(1.0,))
    with pytest.raises(dx.ValidationError):
        _RuleSystem(binary_rules=("a", "b"), binary_weights=(1.0,))
