"""Tests for generic Model classes via PEP 695 syntax."""

import didactic.api as dx

# -- a parametric model declared with PEP 695 --------------------------


class Box[T](dx.Model):
    """A trivial generic container."""

    contents: T
    label: str = ""


def test_unparameterised_generic_carries_field_specs() -> None:
    # Box (without [T] applied) still has field specs, but `contents`
    # has a TypeVar annotation. Generic models without concrete
    # parameterisation cannot be instantiated; they're authoring sugar.
    assert "contents" in Box.__field_specs__
    assert "label" in Box.__field_specs__


# -- a non-generic concrete subclass to verify the surface ------------


class IntBox(dx.Model):
    """Hand-written equivalent of ``Box[int]`` for v0.0.2."""

    contents: int
    label: str = ""


def test_concrete_subclass_round_trips() -> None:
    b = IntBox(contents=42, label="answer")
    assert b.contents == 42
    assert b.label == "answer"
    assert IntBox.model_validate(b.model_dump()) == b
