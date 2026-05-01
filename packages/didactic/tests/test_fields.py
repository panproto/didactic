"""Unit tests for the FieldSpec / field() / Annotated reader layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
from annotated_types import Ge, Le, MinLen

from didactic.fields._fields import (
    MISSING,
    Field,
    FieldSpec,
    field,
    read_annotated_metadata,
)
from didactic.types._types import classify


def test_field_default() -> None:
    f = field(default=0)
    assert isinstance(f, Field)
    assert f.default == 0
    assert f.default_factory is None


def test_field_factory() -> None:
    # The ``default_factory`` overload returns ``T`` so callers can write
    # ``items: list[int] = field(default_factory=list)``. The runtime
    # value is the underlying ``Field`` descriptor; the cast restores
    # that view so we can poke its internals.
    f = cast("Field", field(default_factory=list))
    assert isinstance(f, Field)
    assert f.default is MISSING
    assert f.default_factory is list


def test_field_default_and_factory_rejected() -> None:
    # Both kwargs together intentionally violates the overload signatures;
    # the runtime check inside ``field`` raises ``TypeError``.
    bad = cast("Callable[..., Field]", field)
    with pytest.raises(TypeError):
        bad(default=0, default_factory=list)


def test_field_metadata_passes_through() -> None:
    f = field(
        description="primary id",
        examples=("u1", "u2"),
        nominal=True,
        deprecated=False,
    )
    assert isinstance(f, Field)
    assert f.description == "primary id"
    assert f.examples == ("u1", "u2")
    assert f.nominal is True


def test_read_annotated_simple() -> None:
    meta = read_annotated_metadata(Annotated[int, Ge(0), Le(127)])
    assert meta.description is None
    # both Ge and Le produce one axiom each
    assert len(meta.axioms) == 2
    assert any("x >= 0" in a for a in meta.axioms)
    assert any("x <= 127" in a for a in meta.axioms)


def test_read_annotated_minlen() -> None:
    meta = read_annotated_metadata(Annotated[str, MinLen(3)])
    assert any("len(x) >= 3" in a for a in meta.axioms)


def test_read_annotated_unknown_metadata_to_extras() -> None:
    class Custom:
        pass

    custom = Custom()
    meta = read_annotated_metadata(Annotated[int, custom])
    assert "Custom" in meta.extras


def test_read_plain_type() -> None:
    meta = read_annotated_metadata(int)
    assert meta.description is None
    assert meta.axioms == ()
    assert meta.extras == {}


def test_field_spec_required() -> None:
    spec = FieldSpec(
        name="id",
        annotation=str,
        translation=classify(str),
    )
    assert spec.is_required
    assert spec.sort == "String"


def test_field_spec_with_default() -> None:
    spec = FieldSpec(
        name="display_name",
        annotation=str,
        translation=classify(str),
        default="",
    )
    assert not spec.is_required
    assert spec.make_default() == ""


def test_field_spec_with_factory() -> None:
    spec = FieldSpec(
        name="tags",
        annotation=tuple[str, ...],
        translation=classify(tuple[str, ...]),
        default_factory=tuple,
    )
    assert not spec.is_required
    assert spec.make_default() == ()
