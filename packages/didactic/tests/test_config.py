"""Tests for ``ModelConfig`` and the class-creation config-resolution path."""

# Test class is registered via metaclass side effect; the local name is
# deliberately discarded.
from typing import TYPE_CHECKING, cast

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue


def test_default_config_present_on_plain_model() -> None:
    class Plain(dx.Model):
        id: str

    assert Plain.__model_config__ == dx.DEFAULT_CONFIG
    assert Plain.__model_config__.extra == "forbid"
    assert Plain.__model_config__.strict is True


def test_explicit_attribute_form() -> None:
    class WithAttr(dx.Model):
        __model_config__ = dx.ModelConfig(title="WithAttr", description="test")
        id: str

    assert WithAttr.__model_config__.title == "WithAttr"
    assert WithAttr.__model_config__.description == "test"


def test_class_kwarg_form() -> None:
    class WithKwarg(dx.Model, title="WithKwarg"):
        id: str

    assert WithKwarg.__model_config__.title == "WithKwarg"


def test_kwarg_overrides_attribute() -> None:
    class Both(dx.Model, title="kwarg-wins"):
        __model_config__ = dx.ModelConfig(title="attr-loses")
        id: str

    assert Both.__model_config__.title == "kwarg-wins"


def test_extra_allow_raises() -> None:
    """``extra="allow"`` is rejected at config construction.

    The frozen-Model contract has no settled storage path for unknown
    fields; ``"allow"`` is reserved until that's resolved.
    """
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        dx.ModelConfig(extra="allow")


def test_invalid_extra_value() -> None:
    with pytest.raises(ValueError, match="must be"):
        dx.ModelConfig(extra="bogus")  # type: ignore[arg-type]


def test_strict_false_reserved() -> None:
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        dx.ModelConfig(strict=False)


def test_populate_by_name_reserved() -> None:
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        dx.ModelConfig(populate_by_name=True)


def test_invalid_attribute_type_rejected() -> None:
    with pytest.raises(TypeError, match="must be a ModelConfig"):

        class Bad(dx.Model):
            # ``cast`` smuggles a non-ModelConfig value past the static
            # type so the runtime guard fires.
            __model_config__ = cast("dx.ModelConfig", "not a config")
            id: str

        assert Bad is not None  # registration is the test


def test_inheritance_carries_config() -> None:
    class Base(dx.Model, title="Base"):
        id: str

    class Child(Base):
        name: str = ""

    # child inherits the parent's config when none is specified
    assert Child.__model_config__.title == "Base"


# -- extra="ignore" --------------------------------------------------------


class _Strict(dx.Model):
    """Default ``extra="forbid"`` model for negative-test contrast."""

    known: int = 0


class _Lenient(dx.Model, extra="ignore"):
    """Drops unknown kwargs at construction; still strict for declared fields."""

    known: int = 0


def test_extra_forbid_rejects_unknown_kwarg() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        _Strict.model_validate({"known": 1, "unknown": 2})
    assert any(e.type == "extra_field" for e in exc.value.entries)


def test_extra_ignore_accepts_unknown_kwarg() -> None:
    """``extra="ignore"`` constructs successfully; unknown kwargs are dropped."""
    instance = _Lenient.model_validate({"known": 1, "unknown": 2, "also_unknown": "x"})
    assert instance.known == 1


def test_extra_ignore_drops_unknowns_from_dump() -> None:
    """Dropped kwargs never enter storage and never appear in model_dump."""
    instance = _Lenient.model_validate({"known": 1, "unknown": 2})
    payload = instance.model_dump()
    assert "unknown" not in payload
    assert payload == {"known": 1}


def test_extra_ignore_round_trips_via_model_validate() -> None:
    """``model_validate`` of an external dict drops unknown keys."""
    instance = _Lenient.model_validate({"known": 7, "vendor_added": "telemetry"})
    assert instance.known == 7
    assert instance.model_dump() == {"known": 7}
    # round-trip through dump and reload sees no resurrected unknown
    again = _Lenient.model_validate(instance.model_dump())
    assert again == instance


def test_extra_ignore_with_method_still_strict() -> None:
    """``with_()`` rejects unknown kwargs even when ``extra="ignore"``.

    Naming a field explicitly in ``with_`` is always a programming
    error; the lenient policy applies only at construction-from-
    external-data boundaries. Unpack from a dict so the unknown
    kwarg name slips past the static check the runtime guard tests.
    """
    instance = _Lenient(known=1)
    # ``with_`` is statically typed; a dynamically-built kwargs dict
    # bypasses the keyword-name check the runtime guard tests.
    bad_kwargs: dict[str, FieldValue] = {"unknown": 2}
    with pytest.raises(dx.ValidationError) as exc:
        instance.with_(**bad_kwargs)
    assert any(e.type == "extra_field" for e in exc.value.entries)


def test_extra_ignore_does_not_break_required_field_validation() -> None:
    """Required-field validation runs before the unknown-kwarg dispatch."""

    class _Required(dx.Model, extra="ignore"):
        required: str  # no default

    with pytest.raises(dx.ValidationError) as exc:
        _Required.model_validate({"unknown": "x"})
    assert any(e.type == "missing_required" for e in exc.value.entries)


def test_extra_ignore_inherited_through_subclass() -> None:
    """A subclass of an ``extra="ignore"`` model inherits the policy."""

    class _Sub(_Lenient):
        extra_field: str = "default"

    instance = _Sub.model_validate({"known": 1, "vendor": "x"})
    assert instance.known == 1
    assert instance.extra_field == "default"
    assert "vendor" not in instance.model_dump()
