"""Field typed as ``A | B`` where both arms are ``TaggedUnion`` roots.

Pins the v0.5.3 multi-root union: dispatch on the shared
discriminator across every root's variant registry. Required to be
disjoint across roots.
"""

from __future__ import annotations

from typing import Literal

import pytest

import didactic.api as dx
from didactic.types._types import TypeNotSupportedError


class _A(dx.TaggedUnion, discriminator="kind"):
    pass


class _A1(_A):
    name: str
    kind: Literal["a1"] = "a1"


class _B(dx.TaggedUnion, discriminator="kind"):
    pass


class _B1(_B):
    name: str
    kind: Literal["b1"] = "b1"


class _Combo(dx.Model):
    items: tuple[_A | _B, ...] = ()


def test_union_of_tagged_unions_constructs_with_either_root() -> None:
    c = _Combo(items=(_A1(name="x"), _B1(name="y"), _A1(name="z")))
    types = [type(item).__name__ for item in c.items]
    assert types == ["_A1", "_B1", "_A1"]


def test_union_of_tagged_unions_round_trips_through_json() -> None:
    c = _Combo(items=(_A1(name="x"), _B1(name="y")))
    out = _Combo.model_validate_json(c.model_dump_json())
    types = [type(item).__name__ for item in out.items]
    assert types == ["_A1", "_B1"]


def test_union_of_tagged_unions_dict_payload_dispatches() -> None:
    c = _Combo(items=({"kind": "a1", "name": "x"},))  # type: ignore[arg-type]
    assert isinstance(c.items[0], _A1)
    assert c.items[0].name == "x"


def test_union_of_tagged_unions_unknown_discriminator_rejected() -> None:
    """Unregistered discriminator value surfaces as an error.

    The raw error type is ``KeyError`` (bubbles from ``decode_one``);
    matches the existing single-root TaggedUnion's behaviour, so the
    test is intentionally permissive on the exception class.
    """
    with pytest.raises((dx.ValidationError, KeyError)):
        _Combo.model_validate_json('{"items": [{"kind": "missing", "name": "z"}]}')


# -- mismatched-discriminator and overlap errors are loud --------------


class _DiffA(dx.TaggedUnion, discriminator="kind"):
    pass


class _DiffA1(_DiffA):
    val: int
    kind: Literal["x"] = "x"


class _DiffB(dx.TaggedUnion, discriminator="type"):
    pass


class _DiffB1(_DiffB):
    val: int
    type: Literal["y"] = "y"


# pin both as referenced; their construction registers them on _DiffA / _DiffB.
_ = (_DiffA1, _DiffB1)


def test_union_of_tagged_unions_mismatched_discriminator_rejected() -> None:
    """Two roots with different discriminator names cannot share a field."""
    with pytest.raises(TypeNotSupportedError, match="discriminator field name"):

        class _Bad(dx.Model):
            x: _DiffA | _DiffB

        _ = _Bad


# Overlap is reported at the moment the field encoder runs (lazy), since
# the live registry is consulted on every encode/decode.


class _OvA(dx.TaggedUnion, discriminator="kind"):
    pass


class _OvA1(_OvA):
    n: int
    kind: Literal["dup"] = "dup"


class _OvB(dx.TaggedUnion, discriminator="kind"):
    pass


class _OvB1(_OvB):
    n: int
    kind: Literal["dup"] = "dup"


# pin _OvB1 as referenced; the class side-effects (registering on _OvB)
# are what the overlap-detection test exercises.
_ = _OvB1


class _OvHolder(dx.Model):
    x: _OvA | _OvB | None = None


def test_union_of_tagged_unions_value_overlap_rejected_on_encode() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _OvHolder(x=_OvA1(n=1))
    msg = exc.value.entries[0].msg
    assert "overlapping discriminator value" in msg
