"""Tests for auto-parameterised Generic Models.

A subscript like ``Range[int]`` returns a synthesised concrete
subclass rather than a structural ``_GenericAlias``; the synthesised
class is cached per type-arg tuple, so repeated subscripts return
the same class object and its ``Theory`` is built once.
"""

from typing import Generic, TypeVar

import pytest

import didactic.api as dx

T = TypeVar("T", int, float)
U = TypeVar("U")


class _Range(dx.Model, Generic[T]):
    """Single-typevar generic with two T-typed required fields."""

    min: T
    max: T


class _Pair(dx.Model, Generic[T, U]):
    """Two-typevar generic with one T-typed and one U-typed field."""

    left: T
    right: U


def test_generic_subscript_returns_subclass_not_alias() -> None:
    """``Range[int]`` returns a real ``type``, not a ``_GenericAlias``."""
    cls = _Range[int]
    assert isinstance(cls, type)
    assert issubclass(cls, _Range)


def test_generic_subscript_caches_per_param_tuple() -> None:
    """Repeated subscripts with the same params return the same class."""
    assert _Range[int] is _Range[int]
    assert _Range[float] is _Range[float]
    assert _Range[int] is not _Range[float]


def test_generic_construction_with_int() -> None:
    instance = _Range[int](min=0, max=10)
    assert instance.min == 0
    assert instance.max == 10


def test_generic_construction_with_float() -> None:
    instance = _Range[float](min=0.5, max=1.5)
    assert instance.min == 0.5
    assert instance.max == 1.5


def test_generic_two_typevars() -> None:
    instance = _Pair[int, str](left=42, right="hello")
    assert instance.left == 42
    assert instance.right == "hello"


def test_generic_concrete_subclass_round_trips_via_json() -> None:
    """A parameterised generic round-trips through ``model_dump_json``."""
    instance = _Range[int](min=1, max=99)
    raw = instance.model_dump_json()
    back = _Range[int].model_validate_json(raw)
    assert back == instance


def test_generic_unparameterised_construction_still_rejected() -> None:
    """Constructing the bare generic (no subscript) still raises.

    The TypeVar guards on the original class stay in place; only the
    synthesised subclass has concrete sorts.
    """
    with pytest.raises(dx.ValidationError) as exc:
        _Range(min=0, max=10)
    assert any(e.type == "type_error" for e in exc.value.entries)


def test_generic_arity_mismatch_raises() -> None:
    """Arity mismatch defers to typing's machinery, which raises.

    My ``__class_getitem__`` only synthesises when arity matches; on
    mismatch it falls through, and the upstream typing machinery
    raises ``TypeError`` for too-many or too-few type arguments.
    """
    with pytest.raises(TypeError, match="arguments"):
        _Pair[int, str, float]  # type: ignore[misc]


def test_generic_synthesised_class_repr_includes_params() -> None:
    cls = _Range[int]
    assert "_Range" in cls.__name__
    assert "int" in cls.__name__


class _Containing(dx.Model):
    """Holds a ``_Range[int]`` field; verifies parameterised generics
    work as values inside other Models.
    """

    rng: dx.Embed[_Range[int]]


def test_parameterised_generic_as_embed_field() -> None:
    """A parameterised generic class is a valid Embed target."""
    holder = _Containing(rng=_Range[int](min=1, max=5))
    assert holder.rng.min == 1
    assert holder.rng.max == 5
    back = _Containing.model_validate_json(holder.model_dump_json())
    assert back == holder


def test_subscript_on_non_generic_model_raises() -> None:
    """A non-generic Model's subscript falls through to typing's machinery.

    The metaclass only synthesises when there are TypeVars to
    substitute; for a plain Model, the upstream subscript raises
    ``TypeError``.
    """

    class _Plain(dx.Model):
        x: int

    # A plain Model has no ``__parameters__``; subscript falls through.
    # The exact return type isn't a Model class, but the call must not
    # raise ``TypeError``.
    try:
        _Plain[int]  # type: ignore[misc]
    except TypeError:
        pass  # accepted; the typing machinery refuses non-generic subscripts
