"""Recursive / mutually-recursive TaggedUnion fields.

Pins two fixes:

- JSON round-trip dispatches dict payloads through the discriminator
  so nested TaggedUnion-typed fields reconstitute correctly when
  ``model_validate_json`` walks a payload that carries the union as
  a dict (no envelope, just the variant's natural shape with the
  discriminator key).
- The variant registry is consulted *live* from ``cls.__variants__``
  at encode/decode time, not snapshotted at field-classify time. This
  means variants registered after a field's parent class is defined
  (the canonical case is mutually recursive AST nodes) participate
  fully.
"""

from __future__ import annotations

from typing import Literal

import pytest

import didactic.api as dx


class _N(dx.TaggedUnion, discriminator="kind"):
    pass


class _Lit(_N):
    kind: Literal["lit"]
    value: int


class _BinOp(_N):
    """Defined before ``_ListLit``; carries ``_N``-typed children.

    Pins the late-registration fix: ``_BinOp`` was classified when
    ``_N.__variants__`` only contained ``_Lit`` and ``_BinOp``, but
    ``_ListLit`` (registered later) must still be a legal child.
    """

    kind: Literal["binop"]
    op: str
    left: _N
    right: _N


class _ListLit(_N):
    kind: Literal["list_lit"]
    elements: tuple[int, ...] = ()


def test_json_round_trip_through_nested_union_field() -> None:
    """``model_validate_json`` reconstructs nested variants correctly."""
    node = _BinOp(
        kind="binop",
        op="+",
        left=_Lit(kind="lit", value=1),
        right=_Lit(kind="lit", value=2),
    )
    payload = node.model_dump_json()
    out = _N.model_validate_json(payload)
    assert isinstance(out, _BinOp)
    assert out.left == _Lit(kind="lit", value=1)
    assert out.right == _Lit(kind="lit", value=2)


def test_late_registered_variant_is_legal_child() -> None:
    """``_ListLit`` (defined after ``_BinOp``) can sit inside ``_BinOp.left``."""
    node = _BinOp(
        kind="binop",
        op="+",
        left=_Lit(kind="lit", value=1),
        right=_ListLit(kind="list_lit"),
    )
    assert isinstance(node.right, _ListLit)


def test_late_registered_variant_round_trips_json() -> None:
    node = _BinOp(
        kind="binop",
        op="+",
        left=_ListLit(kind="list_lit", elements=(1, 2, 3)),
        right=_Lit(kind="lit", value=0),
    )
    out = _N.model_validate_json(node.model_dump_json())
    assert isinstance(out, _BinOp)
    assert isinstance(out.left, _ListLit)
    assert out.left.elements == (1, 2, 3)


def test_unknown_variant_in_dict_payload_still_rejects() -> None:
    """The dict-dispatch relaxation only matches *registered* discriminator values."""
    with pytest.raises(dx.ValidationError):
        _N.model_validate_json(
            '{"kind": "binop", "op": "+", '
            '"left": {"kind": "missing", "value": 1}, '
            '"right": {"kind": "lit", "value": 2}}'
        )


def test_dict_payload_for_directly_constructed_field() -> None:
    """Construction with a dict child also dispatches via the discriminator.

    The same encoder branch handles both the JSON round-trip path and
    direct ``BinOp(left={"kind": "lit", "value": 1})`` callers.
    """
    node = _BinOp(
        kind="binop",
        op="+",
        left={"kind": "lit", "value": 1},  # type: ignore[arg-type]
        right=_Lit(kind="lit", value=2),
    )
    assert isinstance(node.left, _Lit)
    assert node.left.value == 1
