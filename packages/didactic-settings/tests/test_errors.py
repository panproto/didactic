"""The error hierarchy and the structured attributes each class carries."""

from __future__ import annotations

from pathlib import Path

import pytest

import didactic.api as dx
from didactic.settings import (
    CoercionError,
    ConfigError,
    InterpolationError,
    MissingFragmentError,
    Origin,
    OverrideSyntaxError,
    UnknownKeyError,
    UnknownVariantError,
    compose,
)


def test_hierarchy() -> None:
    assert issubclass(ConfigError, ValueError)
    for cls in (
        UnknownKeyError,
        UnknownVariantError,
        MissingFragmentError,
        OverrideSyntaxError,
        CoercionError,
    ):
        assert issubclass(cls, ConfigError)
    assert issubclass(InterpolationError, ValueError)
    assert not issubclass(InterpolationError, ConfigError)


def test_config_error_path_defaults_to_none() -> None:
    e = ConfigError("m")
    assert str(e) == "m"
    assert e.path is None
    assert ConfigError("m", path="a.b").path == "a.b"


def test_unknown_key_error_attributes() -> None:
    origin = Origin("file", name="x.yaml", path="/x.yaml")
    e = UnknownKeyError(
        "m", path="a.b", allowed=("a", "c"), declared_by=("lstm",), set_by=origin
    )
    assert e.path == "a.b"
    assert e.allowed == ("a", "c")
    assert e.declared_by == ("lstm",)
    assert e.set_by is origin
    bare = UnknownKeyError("m", path="a")
    assert (bare.allowed, bare.declared_by, bare.set_by) == ((), (), None)


def test_unknown_variant_error_attributes() -> None:
    e = UnknownVariantError("m", path="a.kind", value="rnn", registered=(1, "a"))
    assert e.path == "a.kind"
    assert e.value == "rnn"
    assert e.registered == (1, "a")
    assert UnknownVariantError("m", path="a", value=None).registered == ()


def test_missing_fragment_error_attributes() -> None:
    tried = (Path("/a/x.yaml"), Path("/a/x.toml"))
    e = MissingFragmentError(
        "m", group="model.enc", name="x", tried=tried, available=("y",)
    )
    assert e.path is None
    assert e.group == "model.enc"
    assert e.name == "x"
    assert e.tried == tried
    assert e.available == ("y",)


def test_coercion_error_attributes() -> None:
    e = CoercionError("m", path="a.b", expected="int", text="x")
    assert (e.path, e.expected, e.text) == ("a.b", "int", "x")


def test_override_syntax_error_is_a_config_error_without_a_path() -> None:
    e = OverrideSyntaxError("m")
    assert e.path is None


def test_interpolation_error_path() -> None:
    assert InterpolationError("m").path is None
    assert InterpolationError("m", path=("a", 0)).path == ("a", 0)


def test_slotted_schema_cannot_carry_provenance() -> None:
    class Slotted(dx.Model, extra="forbid"):
        __slots__ = ()
        x: int = 0

    with pytest.raises(ConfigError) as info:
        compose(schema=Slotted)
    assert str(info.value) == (
        "Slotted declares __slots__ and cannot carry provenance; drop the slots "
        "declaration or read compose_traced(...).provenance instead"
    )
