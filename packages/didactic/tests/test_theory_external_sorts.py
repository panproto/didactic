"""Every theory didactic emits declares the other models' sorts it names."""

from __future__ import annotations

import types
from typing import TYPE_CHECKING, Literal, cast

import panproto
import pytest

import didactic.api as dx
from didactic.migrations._fingerprint import structural_fingerprint
from didactic.theory._theory import build_theory, build_theory_spec

if TYPE_CHECKING:
    from pathlib import Path


class Leaf(dx.Model):
    n: int


class Child(dx.Model):
    label: str
    leaf: dx.Embed[Leaf]


class OptionalEmbed(dx.Model):
    child: dx.Embed[Child] | None = None


class RequiredEmbed(dx.Model):
    child: dx.Embed[Child]


class RefEdge(dx.Model):
    child: dx.Ref[Child]


class Shape(dx.TaggedUnion, discriminator="kind"):
    pass


class Circle(Shape):
    kind: Literal["circle"] = "circle"
    center: dx.Embed[Leaf]


class HasShape(dx.Model):
    shape: Shape


class Reads(dx.Model):
    child: dx.Embed[Child]


class Writes(dx.Model):
    leaf: dx.Ref[Leaf]


class Both(Reads, Writes):
    note: str


@pytest.mark.parametrize(
    ("model", "external"),
    [
        (OptionalEmbed, {"Child"}),
        (RequiredEmbed, {"Child"}),
        (RefEdge, {"Child"}),
        (Circle, {"Leaf"}),
        (HasShape, {"Circle"}),
        (Both, {"Child", "Leaf"}),
    ],
)
def test_theory_declares_the_sorts_of_other_models(
    model: type[dx.Model], external: set[str]
) -> None:
    theory = model.__theory__
    panproto.typecheck_theory(theory)
    declared = {cast("str", sort["name"]) for sort in theory.sorts}
    in_spec = {cast("str", sort["name"]) for sort in build_theory_spec(model)["sorts"]}
    assert declared - in_spec == external


def test_the_spec_and_its_fingerprint_name_no_external_sort() -> None:
    spec = build_theory_spec(OptionalEmbed)
    assert [sort["name"] for sort in spec["sorts"]] == ["OptionalEmbed"]
    assert structural_fingerprint(spec) == (
        structural_fingerprint(build_theory_spec(OptionalEmbed))
    )


def _names(theory: panproto.Theory) -> tuple[set[str], set[tuple[str, str]]]:
    return (
        {cast("str", sort["name"]) for sort in theory.sorts},
        {(cast("str", op["name"]), cast("str", op["output"])) for op in theory.ops},
    )


class Base(dx.Model):
    shared: int


class Left(Base):
    left: int


class Right(Base):
    right: int


def _subclass(
    name: str, bases: tuple[type[dx.Model], ...], **fields: type
) -> type[dx.Model]:
    """Build a Model whose overrides a type checker would refuse to write."""
    namespace = {"__annotations__": fields, "__module__": __name__}
    return cast(
        "type[dx.Model]",
        types.new_class(name, bases, exec_body=lambda ns: ns.update(namespace)),
    )


Overrides = _subclass("Overrides", (Base,), shared=str, other=int)
MixedOverride = _subclass("MixedOverride", (Left, Overrides), own=int)
Redeclares = _subclass("Redeclares", (Left, Right), shared=str)


class Diamond(Left, Right):
    own: int


@pytest.mark.parametrize("model", [Both, Diamond, MixedOverride, Redeclares])
def test_multiple_inheritance_joins_to_the_flat_theory(model: type[dx.Model]) -> None:
    kind = model.__name__
    sorts, ops = _names(build_theory(model))
    spec = build_theory_spec(model)
    assert {cast("str", sort["name"]) for sort in spec["sorts"]} <= sorts
    assert ops == {
        (cast("str", op["name"]), cast("str", op["output"])) for op in spec["ops"]
    }
    assert all(
        [row[1] for row in cast("list[list[str]]", op["inputs"])] == [kind]
        for op in build_theory(model).ops
    )


def test_unrelated_parents_disagreeing_on_a_field_are_rejected() -> None:
    class IntX(dx.Model):
        x: int

    class StrX(dx.Model):
        x: str

    disagrees = _subclass("Disagrees", (IntX, StrX), y=int)
    with pytest.raises(panproto.GatError, match="Disagrees_x"):
        build_theory(disagrees)


def test_a_model_with_an_embedded_field_stores_records(tmp_path: Path) -> None:
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(RequiredEmbed)
    record = RequiredEmbed(child=Child(label="a", leaf=Leaf(n=1)))
    data = tmp_path / "record.json"
    data.write_text(record.model_dump_json())
    repo.add_data(data, key="record")
    repo.commit("record", author="Test <test@example.com>")
    (dataset,) = repo.decoded_data_at("HEAD")
    assert dataset.records == [{"child": {"label": "a", "leaf": {"n": 1}}}]
