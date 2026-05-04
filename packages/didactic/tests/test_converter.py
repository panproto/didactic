"""Tests for the PEP 712 ``converter`` path on ``dx.field``.

Notes
-----
A converter runs *before* type translation and any ``@validates`` hooks.
Failures inside a converter surface as ``ValidationError`` entries
tagged ``type_error``.
"""

# ``converter=int`` passes the ``int`` type as a converter; the
# runtime calls it; pyright sees ``type[int]`` not the call.
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue


# Typed converter helpers. Inline lambdas would be inferred against
# ``FieldValue`` (a wide union) and pyright would not see ``.strip``
# on every branch; the named functions narrow the parameter to the
# field's declared type at the boundary so the body type-checks.
def _strip_lower(v: FieldValue) -> str:
    assert isinstance(v, str)
    return v.strip().lower()


def _strip_each(v: FieldValue) -> tuple[str, ...]:
    assert isinstance(v, tuple)
    return tuple(t.strip() for t in v if isinstance(t, str))


class WithConverter(dx.Model):
    """Model that exercises the converter slot on three field types."""

    name: str = dx.field(converter=_strip_lower)
    # ``int`` itself does not type-check as
    # ``Callable[[FieldValue], FieldValue]``; the lambda routes through
    # the wide ``FieldValue`` union and re-narrows on call.
    count: int = dx.field(default=0, converter=lambda v: int(cast("str", v)))
    tags: tuple[str, ...] = dx.field(default=(), converter=_strip_each)


def test_converter_runs_on_construction() -> None:
    m = WithConverter(name="  HELLO  ", count="42", tags=(" a ", " b "))
    assert m.name == "hello"
    assert m.count == 42
    assert m.tags == ("a", "b")


def test_converter_runs_on_with_() -> None:
    m = WithConverter(name="alice")
    m2 = m.with_(name="  BOB ")
    assert m2.name == "bob"


def test_converter_runs_on_default() -> None:
    # default for `count` is 0 (already int); converter is the identity here
    m = WithConverter(name="alice")
    assert m.count == 0


def test_converter_failure_routes_to_validation_error() -> None:
    # passing a non-numeric string should fail in the int() converter
    with pytest.raises(dx.ValidationError) as exc:
        WithConverter(name="alice", count="not a number")
    assert any(e.type == "type_error" for e in exc.value.entries)


def test_converter_runs_before_encode() -> None:
    # the converter normalises whitespace; the encoded form sees the
    # already-normalised value
    m = WithConverter(name="  Spaces  ")
    dumped = m.model_dump()
    assert dumped["name"] == "spaces"
