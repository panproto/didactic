# Tests build Model classes and feed their Theory specs back through the
# synthesiser; pyright flags class-keyed dicts as potentially unhashable
# (Model is hashable by class identity at runtime). Tracked in
# panproto/didactic#1.
"""Tests for the inbound spec -> Model synthesiser.

The primary correctness contract is a *Theory-spec* round-trip against
didactic's own forward path: for a hand-written ``dx.Model``, the
regenerated class's ``build_theory_spec`` must equal the original's. The
spec is lossy (every non-scalar collapses to ``{"Val": "Str"}``; Ref and
Embed share an edge shape), so equality is on structure, not on the
Python annotations.

The spec-dict round-trip tests run unconditionally. The
``panproto.Theory`` path is guarded with ``importorskip`` because it needs
the panproto runtime.
"""

from typing import Literal, cast

import pytest

import didactic.api as dx
from didactic.synthesis import (
    model_from_spec,
    model_from_theory,
    models_from_specs,
)
from didactic.theory._theory import build_theory_spec


# ---------------------------------------------------------------------------
# representative hand-written models
# ---------------------------------------------------------------------------


class Scalars(dx.Model):
    """Every registered scalar; exercises each ValueKind inverse."""

    s: str
    i: int
    f: float
    b: bool
    by: bytes


class Optionals(dx.Model):
    """Optionals collapse to Str on the forward path."""

    a: str
    maybe: str | None = None
    maybe_int: int | None = None


class Containers(dx.Model):
    """Tuple / frozenset / dict all collapse to Str on the forward path."""

    items: tuple[int, ...]
    tags: frozenset[str]
    by_name: dict[str, int]


class RefTarget(dx.Model):
    """Target of a Ref edge."""

    id: str


class RefHolder(dx.Model):
    """Holds a Ref edge to RefTarget."""

    id: str
    target: dx.Ref[RefTarget]


class EmbedHolder(dx.Model):
    """Holds an Embed edge to RefTarget."""

    id: str
    inner: dx.Embed[RefTarget]


class Node(dx.Model):
    """Mutually-recursive pair with Other."""

    id: str
    other: dx.Ref["Other"]  # noqa: UP037  forward ref; Other is defined below


class Other(dx.Model):
    """Mutually-recursive pair with Node."""

    id: str
    node: dx.Ref[Node]


class InheritBase(dx.Model):
    """Single-inheritance base."""

    id: str


class InheritSub(InheritBase):
    """Single-inheritance child adding a field."""

    extra: int


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _roundtrip(model: type[dx.Model], *, deps: list[type[dx.Model]] | None = None):
    """Synthesise from ``model``'s spec and return the regenerated class.

    ``deps`` are dependency models (Ref/Embed targets, bases) whose specs
    populate the shared registry before ``model`` is synthesised, so edges
    and ``extends`` resolve to real classes.
    """
    registry: dict[str, type[dx.Model]] = {}
    for dep in deps or []:
        model_from_spec(build_theory_spec(dep), registry=registry)
    return model_from_spec(build_theory_spec(model), registry=registry)


# ---------------------------------------------------------------------------
# spec-dict round-trip (no panproto runtime required)
# ---------------------------------------------------------------------------


def test_scalars_spec_roundtrip() -> None:
    regen = _roundtrip(Scalars)
    assert build_theory_spec(regen) == build_theory_spec(Scalars)
    assert set(regen.__field_specs__) == set(Scalars.__field_specs__)


def test_scalars_instance_roundtrip() -> None:
    regen = _roundtrip(Scalars)
    inst = regen(s="x", i=1, f=2.5, b=True, by=b"\x00\x01")
    dumped = inst.model_dump()
    assert dumped["s"] == "x"
    assert dumped["i"] == 1
    # model_validate accepts the dumped dict back
    again = regen.model_validate(dumped)
    assert again == inst


def test_optionals_spec_roundtrip() -> None:
    regen = _roundtrip(Optionals)
    assert build_theory_spec(regen) == build_theory_spec(Optionals)
    assert set(regen.__field_specs__) == set(Optionals.__field_specs__)


def test_containers_spec_roundtrip() -> None:
    # tuple / frozenset / dict all collapse to {"Val": "Str"} on the
    # forward path, so the regenerated str-typed fields produce an
    # identical spec.
    regen = _roundtrip(Containers)
    assert build_theory_spec(regen) == build_theory_spec(Containers)
    assert set(regen.__field_specs__) == set(Containers.__field_specs__)


def test_ref_spec_roundtrip() -> None:
    regen = _roundtrip(RefHolder, deps=[RefTarget])
    assert build_theory_spec(regen) == build_theory_spec(RefHolder)
    assert set(regen.__field_specs__) == set(RefHolder.__field_specs__)
    # the edge op points at the target's primary sort
    op_by_name = {op["name"]: op for op in build_theory_spec(regen)["ops"]}
    assert op_by_name["target"]["output"] == "RefTarget"


def test_embed_spec_roundtrip() -> None:
    # Embed and Ref share an edge shape in the spec, so an Embed model's
    # spec round-trips through a Ref reconstruction.
    regen = _roundtrip(EmbedHolder, deps=[RefTarget])
    assert build_theory_spec(regen) == build_theory_spec(EmbedHolder)
    assert set(regen.__field_specs__) == set(EmbedHolder.__field_specs__)


def test_mutual_recursion_spec_roundtrip() -> None:
    regen = models_from_specs([build_theory_spec(Node), build_theory_spec(Other)])
    assert build_theory_spec(regen["Node"]) == build_theory_spec(Node)
    assert build_theory_spec(regen["Other"]) == build_theory_spec(Other)
    # the edges resolve to the real regenerated classes (not forward strings)
    node_op = {op["name"]: op for op in build_theory_spec(regen["Node"])["ops"]}
    assert node_op["other"]["output"] == "Other"


def test_inheritance_spec_roundtrip() -> None:
    # The forward path FLATTENS single inheritance: the child's spec
    # carries every inherited field inline and ``extends == []`` (the
    # metaclass walks the MRO when collecting field specs). The synthesised
    # child is therefore a flat model with the same fields, and its spec
    # round-trips even though the subclass relationship is not recovered.
    assert build_theory_spec(InheritSub)["extends"] == []
    regen = models_from_specs(
        [build_theory_spec(InheritBase), build_theory_spec(InheritSub)]
    )
    sub = regen["InheritSub"]
    assert build_theory_spec(sub) == build_theory_spec(InheritSub)
    # inherited + own fields are both present (flattened)
    assert set(sub.__field_specs__) == set(InheritSub.__field_specs__)


def test_extends_resolves_to_registered_base() -> None:
    # When a spec DOES carry an ``extends`` (e.g. a hand-authored spec or a
    # future forward path that emits it), the synthesised child really
    # subclasses the registered base.
    base_spec: dict[str, object] = {
        "name": "Animal",
        "extends": [],
        "sorts": [
            {"name": "Animal", "params": [], "kind": "Structural", "closure": "Open"},
            {
                "name": "Animal_legs",
                "params": [],
                "kind": {"Val": "Int"},
                "closure": "Open",
            },
        ],
        "ops": [
            {
                "name": "legs",
                "inputs": [["self", "Animal", "No"]],
                "output": "Animal_legs",
            },
        ],
        "eqs": [],
        "directed_eqs": [],
        "policies": [],
    }
    child_spec: dict[str, object] = {
        "name": "Dog",
        "extends": ["Animal"],
        "sorts": [
            {"name": "Dog", "params": [], "kind": "Structural", "closure": "Open"},
            {
                "name": "Dog_name",
                "params": [],
                "kind": {"Val": "Str"},
                "closure": "Open",
            },
        ],
        "ops": [
            {"name": "name", "inputs": [["self", "Dog", "No"]], "output": "Dog_name"},
        ],
        "eqs": [],
        "directed_eqs": [],
        "policies": [],
    }
    regen = models_from_specs([cast("object", base_spec), cast("object", child_spec)])
    assert issubclass(regen["Dog"], regen["Animal"])
    # the child inherits the base's field plus its own
    assert "legs" in regen["Dog"].__field_specs__
    assert "name" in regen["Dog"].__field_specs__


def test_models_from_specs_returns_all() -> None:
    regen = models_from_specs(
        [
            build_theory_spec(RefTarget),
            build_theory_spec(RefHolder),
            build_theory_spec(EmbedHolder),
        ]
    )
    assert set(regen) == {"RefTarget", "RefHolder", "EmbedHolder"}


def test_name_override() -> None:
    regen = model_from_spec(build_theory_spec(Scalars), name="Renamed")
    assert regen.__name__ == "Renamed"
    assert regen.__schema_kind__ == "Renamed"


def test_synthesised_field_is_required_no_default() -> None:
    # the spec carries no defaults; every reconstructed field is required.
    regen = _roundtrip(Optionals)
    for spec in regen.__field_specs__.values():
        assert spec.is_required


# ---------------------------------------------------------------------------
# closed sum sorts: TaggedUnion fields
# ---------------------------------------------------------------------------


class Kind(dx.TaggedUnion, discriminator="kind"):
    """Two-variant discriminated union used as a field type."""


class IntKind(Kind):
    kind: Literal["int"]
    value: int


class StrKind(Kind):
    kind: Literal["str"]
    text: str


class HasUnion(dx.Model):
    """A model whose field is a TaggedUnion, alongside a scalar."""

    head: Kind
    note: str = ""


class One(dx.TaggedUnion, discriminator="tag"):
    """Single-variant union."""


class OnlyVariant(One):
    tag: Literal["only"]


class HoldsOne(dx.Model):
    x: One


class Many(dx.TaggedUnion, discriminator="t"):
    """Four-variant union exercising constructor order."""


class VariantA(Many):
    t: Literal["a"]


class VariantB(Many):
    t: Literal["b"]


class VariantC(Many):
    t: Literal["c"]


class VariantD(Many):
    t: Literal["d"]


class HoldsMany(dx.Model):
    m: Many


class Sig(dx.TaggedUnion, discriminator="code"):
    """Union whose discriminator pins integer literals."""


class CodeOne(Sig):
    code: Literal[1]


class CodeTwo(Sig):
    code: Literal[2]


class HoldsSig(dx.Model):
    s: Sig


def _union_annotation(model: type[dx.Model], field: str) -> type[dx.TaggedUnion]:
    """Return a field's annotation, narrowed to a TaggedUnion subclass."""
    annotation = model.__field_specs__[field].annotation
    assert isinstance(annotation, type)
    assert issubclass(annotation, dx.TaggedUnion)
    return annotation


def _closed_list(spec: object, sort_name: str) -> list[str]:
    """Pull a closed sum sort's ``Closed`` constructor list from a spec."""
    spec_dict = cast("dict[str, list[dict[str, object]]]", spec)
    sort = next(s for s in spec_dict["sorts"] if s["name"] == sort_name)
    closure = cast("dict[str, list[str]]", sort["closure"])
    return closure["Closed"]


def test_tagged_union_field_spec_roundtrip() -> None:
    # the gap closed: a TaggedUnion-bearing model's forward spec round-trips
    # through the inbound synthesiser at the theory-spec level.
    regen = model_from_spec(build_theory_spec(HasUnion))
    assert build_theory_spec(regen) == build_theory_spec(HasUnion)


def test_tagged_union_field_is_a_union_root() -> None:
    regen = model_from_spec(build_theory_spec(HasUnion))
    head_type = _union_annotation(regen, "head")
    assert head_type.__discriminator__ == "kind"
    # the union sort name is preserved (the forward path names it after the
    # union class), and both variants register under their discriminator
    assert head_type.__name__ == "Kind"
    assert set(head_type.__variants__) == {"int", "str"}


def test_tagged_union_variant_names_preserved() -> None:
    regen = model_from_spec(build_theory_spec(HasUnion))
    head_type = _union_annotation(regen, "head")
    variant_names = {v.__name__ for v in head_type.__variants__.values()}
    assert variant_names == {"IntKind", "StrKind"}


def test_tagged_union_constructor_ops_not_treated_as_fields() -> None:
    # the per-variant constructor ops (Kind_int, Kind_str) precede the field
    # accessors in the ops list; they must not become fields of the model.
    regen = model_from_spec(build_theory_spec(HasUnion))
    assert set(regen.__field_specs__) == {"head", "note"}


def test_tagged_union_single_variant_roundtrip() -> None:
    regen = model_from_spec(build_theory_spec(HoldsOne))
    assert build_theory_spec(regen) == build_theory_spec(HoldsOne)


def test_tagged_union_many_variants_preserve_order() -> None:
    orig = build_theory_spec(HoldsMany)
    regen = model_from_spec(orig)
    got = build_theory_spec(regen)
    assert got == orig
    # constructor order is preserved (Closed list order is significant)
    assert _closed_list(got, "Many") == ["Many_a", "Many_b", "Many_c", "Many_d"]


def test_tagged_union_field_used_twice_shares_one_sort() -> None:
    class TwoFields(dx.Model):
        first: Kind
        second: Kind

    orig = build_theory_spec(TwoFields)
    regen = model_from_spec(orig)
    assert build_theory_spec(regen) == orig
    # only one Kind sort is emitted even though two fields use it
    got = cast("dict[str, list[dict[str, object]]]", build_theory_spec(regen))
    kind_sorts = [s for s in got["sorts"] if s["name"] == "Kind"]
    assert len(kind_sorts) == 1


def test_tagged_union_non_string_discriminator_value_collapses_to_str() -> None:
    # a Literal[int] discriminator produces constructor names like Sig_1;
    # the synthesiser rebuilds the value as the string "1". The constructor
    # name round-trips, so the spec is preserved even though the Python
    # discriminator value type (int) is not.
    orig = build_theory_spec(HoldsSig)
    regen = model_from_spec(orig)
    assert build_theory_spec(regen) == orig
    regen_union = _union_annotation(regen, "s")
    # rebuilt discriminator values are strings
    assert set(regen_union.__variants__) == {"1", "2"}


def test_tagged_union_variant_registered_for_cross_reference() -> None:
    # a variant payload sort is registered, so another model's Ref to it
    # resolves to the same synthesised class object.
    registry: dict[str, type[dx.Model]] = {}
    model_from_spec(build_theory_spec(HasUnion), registry=registry)
    assert "IntKind" in registry
    assert "Kind" in registry
    assert issubclass(registry["IntKind"], registry["Kind"])


# ---------------------------------------------------------------------------
# closed sum sorts: Model-ref recursive aliases
# ---------------------------------------------------------------------------


class AliasLeaf(dx.Model):
    """Model arm of a recursive alias."""

    v: str


type _Tree = str | int | AliasLeaf | tuple["_Tree", ...] | dict[str, "_Tree"]
type _P = str | AliasLeaf | tuple["_P", ...]
type _D = int | AliasLeaf | dict[str, "_D"] | list["_D"]


class HasAlias(dx.Model):
    """A model whose field is a Model-ref recursive alias."""

    body: _Tree


class HoldsP(dx.Model):
    p: _P


class HoldsD(dx.Model):
    d: _D


def test_recursive_alias_field_spec_roundtrip() -> None:
    regen = models_from_specs(
        [build_theory_spec(AliasLeaf), build_theory_spec(HasAlias)]
    )
    assert build_theory_spec(regen["HasAlias"]) == build_theory_spec(HasAlias)


def test_recursive_alias_resolves_model_arm_from_registry() -> None:
    # AliasLeaf is passed first; the alias arm resolves to the real class.
    regen = models_from_specs(
        [build_theory_spec(AliasLeaf), build_theory_spec(HasAlias)]
    )
    assert "AliasLeaf" in regen
    # the alias arm constructor input names the real arm model's sort
    spec = cast(
        "dict[str, list[dict[str, object]]]", build_theory_spec(regen["HasAlias"])
    )
    op = next(o for o in spec["ops"] if o["name"] == "_Tree_aliasleaf")
    inputs = cast("list[list[str]]", op["inputs"])
    assert inputs[0][1] == "AliasLeaf"


def test_recursive_alias_arm_model_stubbed_when_absent() -> None:
    # synthesising HasAlias alone (no AliasLeaf spec) still round-trips: the
    # arm model is stood up as a fieldless stub named after the arm sort.
    regen = model_from_spec(build_theory_spec(HasAlias))
    assert build_theory_spec(regen) == build_theory_spec(HasAlias)


def test_recursive_alias_only_primitives_and_one_model() -> None:
    regen = models_from_specs([build_theory_spec(AliasLeaf), build_theory_spec(HoldsP)])
    assert build_theory_spec(regen["HoldsP"]) == build_theory_spec(HoldsP)


def test_recursive_alias_dict_and_list_arms() -> None:
    regen = models_from_specs([build_theory_spec(AliasLeaf), build_theory_spec(HoldsD)])
    assert build_theory_spec(regen["HoldsD"]) == build_theory_spec(HoldsD)


def test_recursive_alias_field_is_a_sum_translation() -> None:
    regen = model_from_spec(build_theory_spec(HasAlias))
    # the rebuilt body field classifies back to a sum (closed sum sort),
    # not an edge or scalar
    body_spec = regen.__field_specs__["body"]
    assert body_spec.translation.inner_kind == "sum"


# ---------------------------------------------------------------------------
# closed sum sorts: forward references, cycles, multi-model graphs
# ---------------------------------------------------------------------------


class Pointer(dx.Model):
    """Holds a Ref to a union variant defined by HasUnion's synthesis."""

    id: str
    to: dx.Ref[IntKind]


def test_recursive_alias_arm_resolves_in_reverse_order() -> None:
    # HasAlias passed BEFORE AliasLeaf: the topo sort orders the arm model
    # first, so the arm still resolves and the spec round-trips.
    regen = models_from_specs(
        [build_theory_spec(HasAlias), build_theory_spec(AliasLeaf)]
    )
    assert build_theory_spec(regen["HasAlias"]) == build_theory_spec(HasAlias)
    assert "AliasLeaf" in regen


def test_union_variant_referenced_by_edge_elsewhere() -> None:
    # a separate model holds a Ref to a union variant; both resolve through
    # the shared registry to the same class object.
    regen = models_from_specs([build_theory_spec(HasUnion), build_theory_spec(Pointer)])
    assert build_theory_spec(regen["Pointer"]) == build_theory_spec(Pointer)
    # the edge target is the variant class registered by the union synthesis
    spec = cast(
        "dict[str, list[dict[str, object]]]", build_theory_spec(regen["Pointer"])
    )
    op = next(o for o in spec["ops"] if o["name"] == "to")
    assert op["output"] == "IntKind"


def test_multi_model_graph_with_union_and_alias() -> None:
    # a graph mixing a TaggedUnion field, a recursive alias field, edges,
    # and a shared leaf round-trips as a whole.
    specs = [
        build_theory_spec(AliasLeaf),
        build_theory_spec(HasUnion),
        build_theory_spec(HasAlias),
        build_theory_spec(RefTarget),
        build_theory_spec(RefHolder),
    ]
    regen = models_from_specs(specs)
    assert build_theory_spec(regen["HasUnion"]) == build_theory_spec(HasUnion)
    assert build_theory_spec(regen["HasAlias"]) == build_theory_spec(HasAlias)
    assert build_theory_spec(regen["RefHolder"]) == build_theory_spec(RefHolder)


# ---------------------------------------------------------------------------
# closed sum sorts: error paths and edge cases
# ---------------------------------------------------------------------------


def test_discriminator_dropped_by_theory_raises() -> None:
    # mimics the panproto.Theory path: a closed sum sort whose arms are all
    # Model sorts (no value/container helper) and whose discriminator key
    # was dropped. Without the discriminator the union cannot be rebuilt.
    spec: dict[str, object] = {
        "name": "Holder",
        "extends": [],
        "sorts": [
            {"name": "Holder", "params": [], "kind": "Structural", "closure": "Open"},
            {
                "name": "U",
                "params": [],
                "kind": "Structural",
                "closure": {"Closed": ["U_a", "U_b"]},
            },
        ],
        "ops": [
            {"name": "U_a", "inputs": [["v", "VariantA", "No"]], "output": "U"},
            {"name": "U_b", "inputs": [["v", "VariantB", "No"]], "output": "U"},
            {"name": "f", "inputs": [["self", "Holder", "No"]], "output": "U"},
        ],
        "eqs": [],
        "directed_eqs": [],
        "policies": [],
    }
    with pytest.raises(NotImplementedError, match="discriminator"):
        model_from_spec(spec)


def test_non_identifier_sort_name_rejected() -> None:
    # a closed sum sort whose name is not a valid identifier cannot be
    # rebuilt (the alias reconstructor would interpolate it into a `type`
    # statement); reject it cleanly.
    spec: dict[str, object] = {
        "name": "Bad",
        "extends": [],
        "sorts": [
            {"name": "Bad", "params": [], "kind": "Structural", "closure": "Open"},
            {
                "name": "not an ident",
                "params": [],
                "kind": "Structural",
                "closure": {"Closed": ["not an ident_str"]},
            },
        ],
        "ops": [
            {
                "name": "not an ident_str",
                "inputs": [["v", "not an ident__str_value", "No"]],
                "output": "not an ident",
            },
            {"name": "f", "inputs": [["self", "Bad", "No"]], "output": "not an ident"},
        ],
        "eqs": [],
        "directed_eqs": [],
        "policies": [],
    }
    with pytest.raises(ValueError, match="identifier"):
        model_from_spec(spec)


def test_model_from_theory_recovers_recursive_alias() -> None:
    # the panproto.Theory path preserves alias sums (no discriminator key
    # needed): a recursive alias round-trips through a real panproto.Theory.
    pytest.importorskip("panproto")
    from didactic.theory._theory import build_theory

    registry: dict[str, type[dx.Model]] = {}
    model_from_theory(build_theory(AliasLeaf), registry=registry)
    regen = model_from_theory(build_theory(HasAlias), registry=registry)
    assert build_theory_spec(regen) == build_theory_spec(HasAlias)


def test_model_from_theory_tagged_union_raises_helpful() -> None:
    # the panproto.Theory path drops the discriminator key, so a TaggedUnion
    # field cannot be recovered through a Theory; the error points to the
    # spec-dict path.
    pytest.importorskip("panproto")
    from didactic.theory._theory import build_theory

    with pytest.raises(NotImplementedError, match="build_theory_spec"):
        model_from_theory(build_theory(HasUnion))


# ---------------------------------------------------------------------------
# panproto.Theory path (needs the panproto runtime)
# ---------------------------------------------------------------------------


def test_model_from_theory_roundtrip() -> None:
    panproto = pytest.importorskip("panproto")
    from didactic.theory._theory import build_theory

    theory = build_theory(Scalars)
    assert isinstance(theory, panproto.Theory)
    regen = model_from_theory(theory)
    assert build_theory_spec(regen) == build_theory_spec(Scalars)
    assert set(regen.__field_specs__) == set(Scalars.__field_specs__)


def test_model_from_theory_ref_edge() -> None:
    pytest.importorskip("panproto")
    from didactic.theory._theory import build_theory

    registry: dict[str, type[dx.Model]] = {}
    model_from_theory(build_theory(RefTarget), registry=registry)
    regen = model_from_theory(build_theory(RefHolder), registry=registry)
    assert build_theory_spec(regen) == build_theory_spec(RefHolder)
