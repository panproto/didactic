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

from typing import TYPE_CHECKING, Literal

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue, JsonValue


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


def _build_chain(depth: int) -> _N:
    node: _N = _Lit(kind="lit", value=0)
    for _ in range(depth):
        node = _BinOp(kind="binop", op="+", left=node, right=_Lit(kind="lit", value=1))
    return node


def test_recursive_construction_is_linear_not_exponential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building a depth-``D`` recursive TaggedUnion runs ``2*D+1`` constructions.

    A ``TaggedUnion``-typed field keeps its variant's fully expanded wire
    JSON in ``_storage``. Dumping it previously decoded that string back to
    a Model and re-encoded it, re-walking the whole subtree at every
    enclosing level; that round trip made construction ``2**(D+1) - 1``
    ``Model.__init__`` calls (exponential, eventually hanging).
    ``model_dump`` now reads storage directly, so the count is exactly the
    node count.
    """
    from didactic.models._model import Model

    original_init = Model.__init__
    calls = 0

    def counting_init(self: Model, **kwargs: FieldValue | JsonValue) -> None:
        nonlocal calls
        calls += 1
        original_init(self, **kwargs)

    monkeypatch.setattr(Model, "__init__", counting_init)

    for depth in (4, 8, 12, 16):
        calls = 0
        _build_chain(depth)
        # D BinOp nodes + (D + 1) Lit nodes, and no reconstruction beyond them
        assert calls == 2 * depth + 1


def test_recursive_dump_round_trips_at_depth() -> None:
    """A deep chain dumps and reloads to the same wire JSON."""
    node = _build_chain(24)
    wire = node.model_dump_json()
    assert _N.model_validate_json(wire).model_dump_json() == wire
