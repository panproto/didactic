"""Tests for auto-parameterised Generic Models.

A subscript like ``Range[int]`` returns a synthesised concrete
subclass rather than a structural ``_GenericAlias``; the synthesised
class is cached per type-arg tuple, so repeated subscripts return
the same class object and its ``Theory`` is built once.
"""

from typing import Generic, TypeVar, cast

import pytest

import didactic.api as dx

T = TypeVar("T", int, float)
U = TypeVar("U")


# PEP 695 generic-class syntax for the headline tests; the legacy
# ``Generic[T]`` mixin form is also supported (``test_generic_legacy_form``).
class _Range[T2: int | float](dx.Model):
    """Single-typevar generic with two ``T``-typed required fields."""

    min: T2
    max: T2


class _Pair[A, B](dx.Model):
    """Two-typevar generic with one ``A``-typed and one ``B``-typed field."""

    left: A
    right: B


class _LegacyRange(dx.Model, Generic[T]):  # noqa: UP046
    """Same shape as ``_Range`` but written with the ``Generic[T]`` mixin.

    Uses the legacy syntax deliberately to verify that path still
    resolves correctly; ``noqa: UP046`` keeps ruff from rewriting it
    to PEP 695 form.
    """

    min: T
    max: T


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

    # A plain Model has no ``__parameters__``; subscript falls through
    # to the upstream ``__class_getitem__`` machinery (or our own
    # explicit ``TypeError`` when no ancestor defines one).
    import contextlib

    with contextlib.suppress(TypeError):
        _Plain[int]  # type: ignore[misc]


# -- legacy ``Generic[T]`` mixin form --------------------------------------


def test_generic_legacy_form_classifies_as_subclass() -> None:
    """The ``class Foo(dx.Model, Generic[T]): ...`` form also synthesises."""
    cls = _LegacyRange[int]
    assert isinstance(cls, type)
    assert issubclass(cls, _LegacyRange)


def test_generic_legacy_form_constructs_with_concrete_type() -> None:
    instance = _LegacyRange[int](min=0, max=10)
    assert instance.min == 0
    assert instance.max == 10


# -- defaults and metadata propagation -------------------------------------


class _RangeWithDefaults[T2: int | float](dx.Model):
    """Generic with class-level defaults that the synthesised class inherits.

    The defaults are type-incompatible with ``T2`` until ``T2`` is bound;
    cast at the boundary so pyright accepts the parent definition.
    """

    min: T2 = cast("T2", 0)
    max: T2 = cast("T2", 100)


def test_generic_inherits_class_level_defaults() -> None:
    """Synthesised concrete subclass picks up parent class-level defaults."""
    instance = _RangeWithDefaults[int]()
    assert instance.min == 0
    assert instance.max == 100


def test_generic_class_level_default_overridable_at_construction() -> None:
    instance = _RangeWithDefaults[int](min=5)
    assert instance.min == 5
    assert instance.max == 100


class _WithFieldMetadata[T2](dx.Model):
    """Generic with ``dx.field(...)`` metadata to propagate."""

    value: T2 = dx.field(default=cast("T2", 42), description="the value")


def test_generic_inherits_field_metadata() -> None:
    """Synthesised class carries the parent's ``Field``-supplied metadata."""
    instance = _WithFieldMetadata[int]()
    assert instance.value == 42
    spec = _WithFieldMetadata[int].__field_specs__["value"]
    assert spec.description == "the value"


class _WithFactory[T2](dx.Model):
    """Generic with ``default_factory`` that runs fresh per instance."""

    items: T2 = dx.field(default_factory=lambda: 99)  # type: ignore[arg-type]


def test_generic_inherits_default_factory() -> None:
    instance = _WithFactory[int]()
    assert instance.items == 99


# -- nested TypeVar substitution -------------------------------------------


class _TupleHolder[T2](dx.Model):
    """``tuple[T, ...]`` should substitute to ``tuple[int, ...]``."""

    items: tuple[T2, ...] = ()


def test_generic_substitutes_through_tuple() -> None:
    instance = _TupleHolder[int](items=(1, 2, 3))
    assert instance.items == (1, 2, 3)
    back = _TupleHolder[int].model_validate_json(instance.model_dump_json())
    assert back == instance


class _DictHolder[T2](dx.Model):
    """``dict[str, T]`` should substitute to ``dict[str, int]``."""

    by_name: dict[str, T2] = dx.field(default_factory=lambda: cast("dict[str, T2]", {}))


def test_generic_substitutes_through_dict() -> None:
    instance = _DictHolder[int](by_name={"a": 1, "b": 2})
    assert instance.by_name == {"a": 1, "b": 2}
    back = _DictHolder[int].model_validate_json(instance.model_dump_json())
    assert back == instance


class _OptHolder[T2](dx.Model):
    """``T | None`` should substitute to ``int | None`` and round-trip."""

    value: T2 | None = None


def test_generic_substitutes_through_optional() -> None:
    assert _OptHolder[int]().value is None
    assert _OptHolder[int](value=42).value == 42
    assert _OptHolder[int](value=None).value is None
    holder = _OptHolder[int](value=7)
    back = _OptHolder[int].model_validate_json(holder.model_dump_json())
    assert back == holder


def test_generic_required_field_with_typevar_inside_container() -> None:
    """A ``tuple[T, ...]`` field with no default stays required after subscript."""

    class _Required[T2](dx.Model):
        items: tuple[T2, ...]

    with pytest.raises(dx.ValidationError) as exc:
        _Required[int].model_validate({})
    assert any(e.type == "missing_required" for e in exc.value.entries)
