"""Tests for ``ModelConfig`` and the class-creation config-resolution path."""

# Test class is registered via metaclass side effect; the local name is
# deliberately discarded.
# Tracked in panproto/didactic#1.
# pyright: reportUnusedClass=false

import pytest

import didactic.api as dx


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


def test_unsupported_extra_raises() -> None:
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        dx.ModelConfig(extra="ignore")
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
            __model_config__ = "not a config"  # type: ignore[assignment]
            id: str


def test_inheritance_carries_config() -> None:
    class Base(dx.Model, title="Base"):
        id: str

    class Child(Base):
        name: str = ""

    # child inherits the parent's config when none is specified
    assert Child.__model_config__.title == "Base"
