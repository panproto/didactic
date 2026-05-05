"""Tests for ``enum.StrEnum`` / ``enum.IntEnum`` / string- or int-valued
``enum.Enum`` as field types.
"""

from __future__ import annotations

from enum import Enum, IntEnum, StrEnum

import pytest

import didactic.api as dx
from didactic.types._types import TypeNotSupportedError


class _Color(StrEnum):
    RED = "red"
    BLUE = "blue"


class _Size(IntEnum):
    S = 1
    L = 2


class _Shape(Enum):
    CIRCLE = "circle"
    SQUARE = "square"


class _ItemModel(dx.Model):
    color: _Color
    size: _Size
    shape: _Shape


def test_strenum_constructs_and_round_trips() -> None:
    m = _ItemModel(color=_Color.RED, size=_Size.L, shape=_Shape.CIRCLE)
    payload = m.model_dump_json()
    assert '"color": "red"' in payload
    assert '"size": 2' in payload
    assert '"shape": "circle"' in payload
    out = _ItemModel.model_validate_json(payload)
    assert out.color is _Color.RED
    assert out.size is _Size.L
    assert out.shape is _Shape.CIRCLE


def test_strenum_rejects_unknown_value() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _ItemModel.model_validate({"color": "purple", "size": 1, "shape": "circle"})
    assert exc.value.entries[0].loc == ("color",)


class _IntValued(Enum):
    A = 1
    B = 2


class _IntValuedHolder(dx.Model):
    n: _IntValued


def test_int_valued_enum_classifies_via_int_branch() -> None:
    m = _IntValuedHolder(n=_IntValued.A)
    out = _IntValuedHolder.model_validate_json(m.model_dump_json())
    assert out == m


class _Mixed(Enum):
    A = "a"
    B = 2


def test_plain_enum_with_mixed_values_rejected() -> None:
    """Mixed-value ``Enum`` doesn't fit either the str or int branch."""
    with pytest.raises(TypeNotSupportedError):

        class _M(dx.Model):
            x: _Mixed

        _ = _M


def test_strenum_construct_accepts_member_or_value() -> None:
    """Construction with the raw value works through the encoder."""
    m = _ItemModel.model_validate({"color": "blue", "size": 1, "shape": "square"})
    assert m.color is _Color.BLUE
    assert m.size is _Size.S
