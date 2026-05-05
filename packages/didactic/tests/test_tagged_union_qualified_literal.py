"""Variant discriminator accepts every spelling of ``Literal[...]``.

Covers the qualified spelling (``typing.Literal[...]``), aliased
imports (``from typing import Literal as Other``), and the form
under ``from __future__ import annotations``. The discriminator
check used to do a string compare on the annotation source, so any
spelling that didn't render as ``Literal[...]`` was rejected; this
file pins the typing-introspection contract that replaced it.
"""

from __future__ import annotations

import typing
from typing import Literal as Lit

import pytest

import didactic.api as dx


class _Node(dx.TaggedUnion, discriminator="kind"):
    pass


class _LitNode(_Node):
    kind: typing.Literal["lit"]
    value: int


class _VarNode(_Node):
    kind: Lit["var"]
    name: str


def test_qualified_literal_registers_variant() -> None:
    assert _Node.__variants__["lit"] is _LitNode
    inst = _LitNode(kind="lit", value=42)
    assert inst.value == 42


def test_aliased_literal_import_registers_variant() -> None:
    assert _Node.__variants__["var"] is _VarNode
    inst = _VarNode(kind="var", name="x")
    assert inst.name == "x"


def test_dispatch_through_root_for_qualified_literal() -> None:
    instance = _Node.model_validate({"kind": "lit", "value": 7})
    assert isinstance(instance, _LitNode)
    assert instance.value == 7


def test_non_literal_discriminator_still_rejected() -> None:
    """The fix only relaxes the *spelling* check; non-Literal still fails."""
    with pytest.raises(TypeError, match="must be annotated as Literal"):

        class _Bad(_Node):
            kind: str  # not a Literal at all
            extra: int

        _ = _Bad  # silence "unused class" lint; the TypeError prevents creation
