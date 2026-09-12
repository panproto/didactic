"""Every Theory didactic emits passes panproto's theory typechecker.

`panproto.create_theory` deserialises a spec and returns, so it accepts
a theory whose declarations do not hang together. `typecheck_theory`
is the check that does not: it verifies that a closed sort's
constructor list names ops that exist and that no op outside the list
produces that sort, that every operation's implicit parameters are
inferrable, and that every equation typechecks.

didactic shipped Theories that failed it. A `dx.TaggedUnion` field
emitted a `Closed` sum sort and an accessor that outputs it, which the
first condition forbids. Nothing caught it because the checker was not
reachable from Python until panproto 0.72.1.

This module walks one model per translation path and asserts the check
passes, so the class of defect fails here rather than in a consumer.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal, cast
from uuid import UUID

import panproto
import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Mapping

    from didactic.types._typing import JsonValue


class Colour(dx.TaggedUnion, discriminator="kind"):
    """Union root with variants registered below."""


class Red(Colour):
    kind: Literal["red"] = "red"
    intensity: float = 1.0


class Blue(Colour):
    kind: Literal["blue"] = "blue"
    depth: int = 0


class Empty(dx.TaggedUnion, discriminator="kind"):
    """A root that never gains a variant."""


class Target(dx.Model):
    """Plain model used as a Ref and Embed target."""

    tid: str = "t"


class Scalars(dx.Model):
    s: str = ""
    i: int = 0
    f: float = 0.0
    b: bool = False
    d: Decimal = Decimal(0)
    when: dt.datetime = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    day: dt.date = dt.date(2026, 1, 1)
    uid: UUID = UUID(int=0)
    raw: bytes = b""


class Containers(dx.Model):
    items: tuple[int, ...] = ()
    names: dict[str, str] = {}
    tags: frozenset[str] = frozenset()


class Optionals(dx.Model):
    scalar: int | None = None
    ref: dx.Ref[Target] | None = None
    embed: dx.Embed[Target] | None = None
    union: Colour | None = None


class Edges(dx.Model):
    ref: dx.Ref[Target]
    embed: dx.Embed[Target]
    bare: Target


class Unions(dx.Model):
    one: Colour
    many: tuple[Colour, ...] = ()
    named: dict[str, Colour] = {}
    variant_free: Empty | None = None


class Enums(dx.Model):
    choice: Literal["a", "b"] = "a"


TYPECHECK_PAYLOAD = dx.Universe("TypecheckPayload", text=str, number=float)


class Indexed(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | float, TYPECHECK_PAYLOAD.at("kind")]


MODELS: list[type[dx.Model]] = [
    Target,
    Scalars,
    Containers,
    Optionals,
    Edges,
    Unions,
    Enums,
    Indexed,
    Red,
    Blue,
]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_emitted_theory_typechecks(model: type[dx.Model]) -> None:
    """The Theory for each translation path satisfies panproto's checker."""
    panproto.typecheck_theory(model.__theory__)


def test_the_checker_is_actually_running() -> None:
    """A negative control, so a no-op checker cannot make this file pass.

    Without this, a `typecheck_theory` that returned unconditionally
    would leave every assertion above green and the gate worthless.
    """
    broken = panproto.create_theory(
        {
            "name": "Broken",
            "extends": [],
            "sorts": [
                {
                    "name": "S",
                    "params": [],
                    "kind": "Structural",
                    "closure": {"Closed": ["missing_ctor"]},
                }
            ],
            "ops": [],
            "eqs": [],
            "directed_eqs": [],
            "policies": [],
        }
    )
    with pytest.raises(panproto.GatError, match="missing_ctor"):
        panproto.typecheck_theory(broken)


def test_the_gate_would_catch_the_regression_returning() -> None:
    """Rebuild the pre-0.13.0 shape by hand and confirm it is rejected.

    didactic emitted a sum sort closed against its variant constructors
    alongside a field accessor that outputs that sort. Taking the real
    spec for a union-carrying model and putting the closure back is the
    smallest faithful reproduction, and it fails for the reason the
    original did: the accessor produces a closed sort it does not
    construct.
    """
    from didactic.theory._theory import build_theory_spec

    spec = build_theory_spec(Unions)
    for sort in spec["sorts"]:
        constructors = sort.get("constructors")
        if isinstance(constructors, list):
            sort["closure"] = {"Closed": constructors}

    # a TypedDict is assignable to no mapping whose value type is
    # narrower than ``object``, so handing a ``TheorySpec`` to
    # ``create_theory`` needs a cast. ``_theory._spec_payload`` is the
    # same cast at the same boundary, and its docstring carries the
    # reasoning; it is private, so this repeats it rather than reaching
    # across the module.
    payload = cast("Mapping[str, JsonValue]", spec)
    with pytest.raises(panproto.GatError, match="closed sort"):
        panproto.typecheck_theory(panproto.create_theory(payload))
