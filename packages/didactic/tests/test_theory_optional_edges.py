"""An optional field points at the sort it targets, not at ``Maybe <sort>``.

``TypeTranslation.sort`` is a didactic-side descriptor rather than a
bare sort name: the optional wrapper spells it ``Maybe (Ref Target)``.
The edge branches of ``build_theory_spec`` need the sort name, so they
peel the wrapper off and record the optionality on the operation.
``Maybe S`` is not something panproto can resolve: a ``SortExpr``
applies a sort to dependent terms, so there is no ``Maybe`` former to
apply to a sort, and the operation output named a sort no theory
declared.

The container wrappers carry the element translation's auxiliary sorts
through for the same reason: a union behind ``tuple[T, ...]`` is still
part of the model's vocabulary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

import didactic.api as dx
from didactic.theory._theory import build_theory_spec

if TYPE_CHECKING:
    from didactic.types._typing import JsonValue


class Node(dx.TaggedUnion, discriminator="kind"):
    """Sum root used as the target of the optional and container fields."""


class Leaf(Node):
    """The one variant."""

    kind: Literal["leaf"] = "leaf"
    n: int = 0


class Target(dx.Model):
    """Plain model, the target of the Ref and Embed fields."""

    tid: str = "t"


class _OptSum(dx.Model):
    p: Node | None = None


class _OptRef(dx.Model):
    p: dx.Ref[Target] | None = None


class _OptEmbed(dx.Model):
    p: dx.Embed[Target] | None = None


class _TupSum(dx.Model):
    p: tuple[Node, ...] = ()


class _DictSum(dx.Model):
    p: dict[str, Node] = {}


class _BareSum(dx.Model):
    p: Node


def _op(cls: type[dx.Model], name: str) -> dict[str, JsonValue]:
    spec = build_theory_spec(cls)
    (op,) = [o for o in spec["ops"] if cast("str", o["name"]) == name]
    return op


def _sort_names(cls: type[dx.Model]) -> set[str]:
    return {cast("str", s["name"]) for s in build_theory_spec(cls)["sorts"]}


def _referenced_sorts(cls: type[dx.Model]) -> set[str]:
    spec = build_theory_spec(cls)
    return {cast("str", op["output"]) for op in spec["ops"]}


def test_optional_sum_edge_targets_the_union_sort() -> None:
    """``Node | None`` points at ``Node``, like the bare spelling does."""
    assert _op(_OptSum, "p")["output"] == "Node"
    assert _op(_OptSum, "p")["output"] == _op(_BareSum, "p")["output"]


def test_optional_ref_edge_targets_the_referenced_sort() -> None:
    """The ``Ref `` prefix is reachable once ``Maybe`` is peeled off."""
    assert _op(_OptRef, "p")["output"] == "Target"


def test_optional_embed_edge_targets_the_embedded_sort() -> None:
    """Same for the containment edge."""
    assert _op(_OptEmbed, "p")["output"] == "Target"


def test_optionality_is_recorded_on_the_operation() -> None:
    """The fact survives; it just no longer travels inside the sort name."""
    assert _op(_OptSum, "p")["optional"] is True
    assert _op(_OptRef, "p")["optional"] is True
    assert _op(_OptEmbed, "p")["optional"] is True


def test_a_required_edge_carries_no_optional_key() -> None:
    """The key is present only where it says something."""
    assert "optional" not in _op(_BareSum, "p")


def test_no_operation_names_an_undeclared_maybe_sort() -> None:
    """No ``Maybe ...`` reaches panproto as a sort name."""
    for cls in (_OptSum, _OptRef, _OptEmbed, _TupSum, _DictSum):
        assert not [s for s in _referenced_sorts(cls) if s.startswith("Maybe")]


def test_optional_union_field_declares_the_sum_sort() -> None:
    """The edge target is declared, so the reference resolves."""
    assert "Node" in _sort_names(_OptSum)


def test_container_over_a_union_declares_the_sum_sort() -> None:
    """A union behind a tuple or dict stays visible in the Theory."""
    assert "Node" in _sort_names(_TupSum)
    assert "Node" in _sort_names(_DictSum)
    tup_ops = {cast("str", o["name"]) for o in build_theory_spec(_TupSum)["ops"]}
    assert "Node_leaf" in tup_ops


def test_container_field_still_reads_as_an_encoded_value() -> None:
    """Carrying the sum sort through does not change the field's own sort."""
    spec = build_theory_spec(_TupSum)
    by_name = {cast("str", s["name"]): s for s in spec["sorts"]}
    assert by_name["_TupSum_p"]["kind"] == {"Val": "Str"}
    assert _op(_TupSum, "p")["output"] == "_TupSum_p"


def test_every_optional_shape_builds_a_real_theory() -> None:
    """The panproto round-trip accepts each spelling."""
    for cls in (_OptSum, _OptRef, _OptEmbed, _TupSum, _DictSum, _BareSum):
        assert cls.__theory__ is not None
