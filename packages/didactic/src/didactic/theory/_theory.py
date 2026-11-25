"""Bridge between didactic FieldSpecs and ``panproto.Theory``.

This module is the seam where the didactic-side metaclass output
(``__field_specs__`` etc.) meets the panproto runtime. Calling
[build_theory][didactic.theory._theory.build_theory] produces a real
``panproto.Theory`` instance for any [Model][didactic.api.Model] subclass.

Coverage
--------
The builder emits the model's primary sort, one constraint sort per
scalar field, one accessor operation per scalar field, and one
edge/containment operation per ``Ref[T]`` / ``Embed[T]`` / sum-sorted
field. An edge points at the sort the field targets whether or not the
field is optional; ``T | None`` sets an ``optional`` key on the
operation rather than changing the sort it names. The spec leaves the
sort of another model to that model's own theory;
[build_theory][didactic.theory._theory.build_theory] declares every such
sort the spec names, since panproto typechecks a theory against the
sorts it declares. Class
axioms are collected on the Python side; their translation into
panproto ``Equation`` records (parsed via the panproto-Expr parser
into a ``lhs``/``rhs`` Term pair) is not yet implemented, so the
Theory is built with empty ``eqs``.

Architecturally, this module is the only place ``panproto`` is
imported in ``didactic`` proper. The import lives inside the function
so that the rest of the package can be authored against the panproto
contract independently.

See Also
--------
didactic.models._meta : the metaclass that populates __field_specs__.
didactic.fields._fields.FieldSpec : the per-field record consumed here.
"""

# ``_class_axiom_eq`` is a stub for the eqs-emission path that's
# registered later; the local symbol is referenced by its qualname.

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    import panproto

    from didactic.fields._fields import FieldSpec
    from didactic.gadt import GADT, SortExpr, Term
    from didactic.models._model import Model
    from didactic.types._types import TypeTranslation
    from didactic.types._typing import JsonValue


class TheorySpec(TypedDict):
    """The dict-shape produced by ``build_theory_spec``.

    The shape mirrors panproto's Rust-side ``Theory`` deserialiser. Each
    entry list is itself a list of dicts (sorts/ops/eqs records) whose
    individual shapes are documented by panproto.
    """

    name: str
    extends: list[str]
    sorts: list[dict[str, JsonValue]]
    ops: list[dict[str, JsonValue]]
    eqs: list[dict[str, JsonValue]]
    directed_eqs: list[dict[str, JsonValue]]
    policies: list[dict[str, JsonValue]]


def _spec_payload(spec: TheorySpec) -> Mapping[str, JsonValue]:
    """Narrow a ``TheorySpec`` to the mapping shape ``create_theory`` takes.

    Parameters
    ----------
    spec
        A spec dict from ``build_theory_spec``.

    Returns
    -------
    Mapping
        The same dict, typed as ``Mapping[str, JsonValue]``.

    Notes
    -----
    The typing spec makes a ``TypedDict`` assignable to
    ``Mapping[str, object]`` and to no mapping with a narrower value
    type, so handing a ``TheorySpec`` to ``panproto.create_theory``
    (whose parameter is ``Mapping[str, JsonValue]``) needs a cast at
    the boundary. Every ``TheorySpec`` field type is a ``JsonValue``,
    so the cast is sound.
    """
    return cast("Mapping[str, JsonValue]", spec)


# ---------------------------------------------------------------------------
# Spec construction (no panproto runtime required)
# ---------------------------------------------------------------------------


def build_theory_spec(cls: type[Model]) -> TheorySpec:
    """Build a panproto-compatible Theory spec dict for a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass with ``__field_specs__`` and
        ``__schema_kind__`` populated by the metaclass.

    Returns
    -------
    dict
        A dict shaped to be deserialised by panproto's Rust core into
        a ``Theory``. Specifically::

            {
                "name": str,  # the model's class name
                "extends": list[str],  # parent theories (none yet)
                "sorts": list[Sort],  # primary sort + per-field sorts
                "ops": list[Operation],  # field accessors / edges
                "eqs": list[Equation],  # axioms
                "directed_eqs": [],  # rewrites; reserved
                "policies": [],  # merge policies; reserved
            }

    Notes
    -----
    The dict only encodes information available on the didactic side. The
    panproto core may further validate the shape and reject malformed
    specs; in that case, the caller surfaces a ``panproto.GatError``.

    See Also
    --------
    build_theory : produces a real ``panproto.Theory`` from this spec.
    """
    field_specs: dict[str, FieldSpec] = cls.__field_specs__
    return _spec_of_fields(
        _schema_kind(cls), field_specs, _indexed_context(field_specs)
    )


def _spec_of_fields(
    schema_kind: str,
    field_specs: Mapping[str, FieldSpec],
    indexed: _IndexedContext,
) -> TheorySpec:
    """Build the Theory spec of a model with the given fields.

    Parameters
    ----------
    schema_kind
        The model's primary sort name, which also prefixes the name of
        each field's constraint sort.
    field_specs
        The fields to emit, keyed by name.
    indexed
        The dependent telescope of the model. Its parameters are emitted
        on the primary sort whether or not ``field_specs`` holds them.

    Returns
    -------
    dict
        The spec; see
        [build_theory_spec][didactic.theory._theory.build_theory_spec].
    """
    sorts: list[dict[str, JsonValue]] = [_primary_sort(schema_kind, indexed.parameters)]
    ops: list[dict[str, JsonValue]] = []
    # class-level axioms are collected on cls.__class_axioms__ but NOT
    # yet emitted as Theory equations: panproto's `Equation` carries
    # `lhs`/`rhs` Term values, and the surface-syntax -> Term translation
    # is its own piece of work (panproto-Expr-parser hookup).
    eqs: list[dict[str, JsonValue]] = []
    directed_eqs: list[dict[str, JsonValue]] = []

    # A dependent field may reference any user-built GADT. Splice each owner
    # theory once. Unlike ``extends``, this embeds the actual declarations, so
    # ``create_theory`` and the typechecker do not depend on a global registry.
    for gadt in indexed.gadts:
        gadt_spec = gadt.to_spec()
        _merge_named(
            sorts, cast("list[dict[str, JsonValue]]", gadt_spec["sorts"]), "sort"
        )
        _merge_named(
            ops, cast("list[dict[str, JsonValue]]", gadt_spec["ops"]), "operation"
        )
        _merge_named(
            eqs, cast("list[dict[str, JsonValue]]", gadt_spec["eqs"]), "equation"
        )
        _merge_named(
            directed_eqs,
            cast("list[dict[str, JsonValue]]", gadt_spec["directed_eqs"]),
            "directed equation",
        )

    # auxiliary sorts/ops contributed by translations: the Model-ref
    # recursive-alias sum sort, and the TaggedUnion sum sort, which is
    # recomputed here from the live variant registry rather than read
    # from a classify-time snapshot. Deduped by ``name``.
    seen_aux_sorts: set[str] = set()
    seen_aux_ops: set[str] = set()

    for fname, spec in field_specs.items():
        # Every field participating in the dependency telescope is carried as
        # a parameter of the Model sort. Emitting a projection for one would
        # introduce an inhabitant of its (possibly Closed) family outside the
        # family constructor list.
        if fname in indexed.parameter_names:
            continue
        aux_sorts, aux_ops = spec.translation.resolve_auxiliary()
        for aux_sort in aux_sorts:
            sort_name = cast("str", aux_sort["name"])
            if sort_name not in seen_aux_sorts:
                seen_aux_sorts.add(sort_name)
                sorts.append(aux_sort)
        for aux_op in aux_ops:
            op_name = cast("str", aux_op["name"])
            if op_name not in seen_aux_ops:
                seen_aux_ops.add(op_name)
                ops.append(aux_op)
        optional = spec.translation.is_optional
        if spec.translation.inner_kind == "ref":
            # Ref[T] becomes a structural edge from this sort to T's sort
            target_sort = _structural_target(spec.translation, "Ref ")
            ops.append(
                _edge_accessor(
                    fname,
                    schema_kind,
                    target_sort,
                    optional,
                    indexed.parameters,
                )
            )
            continue
        if spec.translation.inner_kind == "embed":
            # Embed[T] becomes a containment edge to T's primary sort.
            # The embedded sort itself is not redeclared here; the target
            # Model's own theory carries it. The containment is structural.
            target_sort = _structural_target(spec.translation, "Embed ")
            ops.append(
                _embed_accessor(
                    fname,
                    schema_kind,
                    target_sort,
                    optional,
                    indexed.parameters,
                )
            )
            continue
        if spec.translation.inner_kind == "sum":
            # A TaggedUnion root, or a Model-ref recursive alias: the sum
            # sort is already in the auxiliary records above, so the field
            # accessor returns it directly (no per-field constraint sort).
            target_sort = _structural_target(spec.translation, "")
            ops.append(
                _edge_accessor(
                    fname,
                    schema_kind,
                    target_sort,
                    optional,
                    indexed.parameters,
                )
            )
            continue
        # constraint sort name follows panproto convention: ParentSort_field
        constraint_sort_name = f"{schema_kind}_{fname}"
        sorts.append(_constraint_sort(constraint_sort_name, spec.translation.sort))
        ops.append(
            _field_accessor(
                fname,
                schema_kind,
                constraint_sort_name,
                indexed.parameters,
            )
        )

    return {
        "name": schema_kind,
        "extends": [],
        "sorts": sorts,
        "ops": ops,
        "eqs": eqs,
        "directed_eqs": directed_eqs,
        "policies": [],
    }


def with_external_sorts(
    spec: TheorySpec, field_specs: Mapping[str, FieldSpec]
) -> TheorySpec:
    """Declare the other models' sorts a spec names.

    Parameters
    ----------
    spec
        The spec of a model with fields ``field_specs``.
    field_specs
        The fields, whose translations say which sorts belong to other
        models: the target of a ``Ref`` or ``Embed`` field, and the
        models a sum-sorted field's constructors take.

    Returns
    -------
    dict
        A spec with one open, parameterless structural sort appended for
        each such sort that ``spec`` does not declare itself.

    Notes
    -----
    The declaration brings the name into scope and says nothing more
    about it; the model's own theory carries its fields. Only the sorts
    of models are declared, so a sort that is undeclared for any other
    reason still fails to typecheck. The result is what panproto is
    given and is not what is fingerprinted: a spec names the same sorts
    with and without it.
    """
    declared = {cast("str", sort["name"]) for sort in spec["sorts"]}
    external: list[str] = []

    def name_sort(name: str) -> None:
        if name not in declared:
            declared.add(name)
            external.append(name)

    for field_spec in field_specs.values():
        translation = field_spec.translation
        if translation.inner_kind == "ref":
            name_sort(_structural_target(translation, "Ref "))
        elif translation.inner_kind == "embed":
            name_sort(_structural_target(translation, "Embed "))
        for op in translation.resolve_auxiliary()[1]:
            # a constructor's inputs are ``[name, sort, implicit]`` rows
            for row in cast("list[list[JsonValue]]", op["inputs"]):
                if isinstance(row[1], str):
                    name_sort(row[1])

    return {
        **spec,
        "sorts": [*spec["sorts"], *(_primary_sort(name) for name in external)],
    }


def _schema_kind(cls: type) -> str:
    """Return ``cls.__schema_kind__``, falling back to the class name."""
    return getattr(cls, "__schema_kind__", cls.__name__)


def _primary_sort(
    name: str, parameters: tuple[tuple[str, SortExpr], ...] = ()
) -> dict[str, JsonValue]:
    """Build the Sort dict for a model's primary vertex.

    Parameters
    ----------
    name
        The sort name; conventionally the class name.
    """
    return {
        "name": name,
        "params": [
            {"name": parameter_name, "sort": sort.to_spec()}
            for parameter_name, sort in parameters
        ],
        "kind": "Structural",
        "closure": "Open",
    }


@dataclass(frozen=True, slots=True)
class _IndexedContext:
    """Dependent Model-sort parameters and the GADTs that define them."""

    parameters: tuple[tuple[str, SortExpr], ...]
    parameter_names: frozenset[str]
    gadts: tuple[GADT, ...]


def _indexed_context(field_specs: dict[str, FieldSpec]) -> _IndexedContext:
    """Derive a topologically ordered telescope from indexed field markers."""
    from didactic.gadt import GADTDeclarationError, Var  # noqa: PLC0415
    from didactic.gadt._indexed import indexed_marker  # noqa: PLC0415

    parameter_sorts: dict[str, SortExpr] = {}
    dependencies: dict[str, tuple[str, ...]] = {}
    owners: list[GADT] = []

    def record(name: str, sort: SortExpr) -> None:
        previous = parameter_sorts.get(name)
        if previous is not None and previous != sort:
            msg = f"index field {name!r} is required at both {previous} and {sort}"
            raise GADTDeclarationError(msg)
        parameter_sorts[name] = sort

    for field_name, spec in field_specs.items():
        marker = indexed_marker(spec)
        if marker is None:
            continue
        if all(owner is not marker.family.owner for owner in owners):
            owners.append(marker.family.owner)
        substitution: dict[str, Term] = {}
        for index_name, family_parameter in zip(
            marker.index_fields, marker.family.parameters, strict=True
        ):
            record(index_name, family_parameter.sort.substitute(substitution))
            substitution[family_parameter.name] = Var(index_name)
        record(field_name, marker.sort)
        dependencies[field_name] = marker.index_fields

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise GADTDeclarationError(
                f"indexed field dependency cycle contains {name!r}"
            )
        visiting.add(name)
        for dependency in dependencies.get(name, ()):
            if dependency in parameter_sorts:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    # Preserve Model declaration order whenever the dependency relation does
    # not force a different order. This keeps fingerprints deterministic.
    for field_name in field_specs:
        if field_name in parameter_sorts:
            visit(field_name)

    parameters = tuple((name, parameter_sorts[name]) for name in ordered)
    return _IndexedContext(parameters, frozenset(parameter_sorts), tuple(owners))


def _merge_named(
    target: list[dict[str, JsonValue]],
    additions: list[dict[str, JsonValue]],
    kind: str,
) -> None:
    """Merge named spec records, accepting equal duplicates only."""
    by_name = {cast("str", item["name"]): item for item in target}
    for addition in additions:
        name = cast("str", addition["name"])
        previous = by_name.get(name)
        if previous is not None:
            if previous != addition:
                msg = f"conflicting {kind} declarations named {name!r}"
                raise ValueError(msg)
            continue
        target.append(addition)
        by_name[name] = addition


# Map from didactic-side sort names to panproto's ValueKind enum.
# Container / optional sorts route to "Str" because their encoded form
# is a JSON string (a stopgap until we represent containers structurally).
_VALUE_KIND_FOR_SORT: dict[str, str] = {
    "String": "Str",
    "Int": "Int",
    "Float64": "Float",
    "Decimal": "Float",
    "Bool": "Bool",
    "Bytes": "Bytes",
    "DateTime": "Str",
    "Date": "Str",
    "Time": "Str",
    "Uuid": "Str",
}


def _value_kind(value_sort: str) -> str:
    """Map a didactic-side sort name to a panproto ``ValueKind`` variant.

    Container / optional / refinement sorts (anything with a space, like
    ``"List Int"``) collapse to ``"Str"`` because their encoded form is
    a JSON string. This is a stopgap pending structural sort support.
    """
    return _VALUE_KIND_FOR_SORT.get(value_sort, "Str")


def _constraint_sort(name: str, value_sort: str) -> dict[str, JsonValue]:
    """Build a Sort dict representing one field's value-typing.

    Parameters
    ----------
    name
        The constraint sort name (typically ``ParentSort_fieldname``).
    value_sort
        The didactic-side sort name (``"String"``, ``"Int"``, ...). The
        builder maps it to the panproto ``ValueKind`` enum.
    """
    return {
        "name": name,
        "params": [],
        "kind": {"Val": _value_kind(value_sort)},
        "closure": "Open",
    }


def _structural_target(translation: TypeTranslation, prefix: str) -> str:
    """Return the sort a structural edge points at, unwrapping the spelling.

    Parameters
    ----------
    translation
        The field's translation. Its ``sort`` is a didactic-side
        descriptor, not a bare sort name: an optional field reads
        ``"Maybe (Ref Target)"`` and a ``Ref`` field ``"Ref Target"``.
    prefix
        The marker prefix to strip for this edge kind (``"Ref "``,
        ``"Embed "``, or ``""`` for a sum sort, which carries none).

    Returns
    -------
    str
        The target sort name.

    Notes
    -----
    Optionality does not change what a field points at, so it is peeled
    off here rather than reaching panproto as part of the sort name.
    ``Maybe S`` is not a sort panproto can resolve: its ``SortExpr``
    applies a sort to dependent *terms*, so there is no ``Maybe`` type
    former to apply to a sort, and an operation output naming one would
    reference a sort no theory declares.
    """
    sort = translation.sort
    if translation.is_optional:
        sort = sort.removeprefix("Maybe ").strip()
        if sort.startswith("(") and sort.endswith(")"):
            sort = sort[1:-1].strip()
    return sort.removeprefix(prefix).strip()


def _edge_accessor(
    field_name: str,
    parent_sort: str,
    target_sort: str,
    optional: bool = False,
    parameters: tuple[tuple[str, SortExpr], ...] = (),
) -> dict[str, JsonValue]:
    """Build an Operation dict for a ``Ref[T]`` edge.

    Parameters
    ----------
    field_name
        The Python attribute name (becomes the edge label).
    parent_sort
        The model's primary sort.
    target_sort
        The referenced model's primary sort name.
    optional
        Whether the field was spelled ``T | None``. Recorded on the
        operation as an informational key; panproto's schema spec
        ignores keys it does not know, and the alternative (folding
        optionality into the output sort name) names a sort nothing
        declares.
    """
    op: dict[str, JsonValue] = {
        "name": field_name,
        "inputs": _model_inputs(parent_sort, parameters),
        "output": target_sort,
    }
    if optional:
        op["optional"] = True
    return op


def _embed_accessor(
    field_name: str,
    parent_sort: str,
    target_sort: str,
    optional: bool = False,
    parameters: tuple[tuple[str, SortExpr], ...] = (),
) -> dict[str, JsonValue]:
    """Build an Operation dict for an ``Embed[T]`` containment edge.

    The structural shape is identical to a ``Ref`` edge; both produce a
    morphism from the parent sort to the target sort. Panproto-side, the
    distinction lives in the operation's containment metadata, which the
    theory builder will start emitting once we round-trip against a
    real ``panproto.Theory`` to learn the canonical key.

    Parameters
    ----------
    field_name
        The Python attribute name (becomes the edge label).
    parent_sort
        The model's primary sort.
    target_sort
        The embedded model's primary sort name.
    optional
        Whether the field was spelled ``T | None``; see
        :func:`_edge_accessor`.
    """
    op: dict[str, JsonValue] = {
        "name": field_name,
        "inputs": _model_inputs(parent_sort, parameters),
        "output": target_sort,
    }
    if optional:
        op["optional"] = True
    return op


def _field_accessor(
    field_name: str,
    parent_sort: str,
    output_sort: str,
    parameters: tuple[tuple[str, SortExpr], ...] = (),
) -> dict[str, JsonValue]:
    """Build an Operation dict for one field-accessor.

    The accessor takes the parent sort and returns the field's value
    sort; this is panproto's standard "field as morphism" pattern.

    Parameters
    ----------
    field_name
        The Python attribute name.
    parent_sort
        The model's primary sort.
    output_sort
        The constraint sort name produced by [_constraint_sort][].
    """
    return {
        "name": field_name,
        "inputs": _model_inputs(parent_sort, parameters),
        "output": output_sort,
    }


def _model_inputs(
    parent_sort: str, parameters: tuple[tuple[str, SortExpr], ...]
) -> list[JsonValue]:
    """Build implicit telescope inputs followed by the explicit model value."""
    from didactic.gadt import SortExpr, Var  # noqa: PLC0415

    inputs: list[JsonValue] = [
        [name, sort.to_spec(), "Yes"] for name, sort in parameters
    ]
    owner_sort = SortExpr(
        parent_sort,
        tuple(Var(name) for name, _ in parameters),
    )
    inputs.append(["self", owner_sort.to_spec(), "No"])
    return inputs


# ---------------------------------------------------------------------------
# Runtime (lazy panproto import)
# ---------------------------------------------------------------------------


def build_theory(cls: type[Model]) -> panproto.Theory:
    """Materialise a ``panproto.Theory`` from a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    panproto.Theory
        The Theory produced by ``panproto.create_theory(spec)``. For a
        class with multiple Model parents, the result is the panproto
        colimit (pushout) of the parents' fields over the ones they
        share; otherwise it's the flat theory built
        from ``cls``'s ``__field_specs__``.

    Raises
    ------
    ImportError
        If ``panproto`` is not installed in the current environment.
    panproto.GatError
        If panproto rejects the spec; usually a sign that didactic's
        translation is producing a malformed dict.

    Notes
    -----
    Single inheritance flattens transparently because the metaclass
    walks the full MRO when collecting field specs; the resulting
    Theory already includes every inherited field. Multiple
    inheritance triggers a real ``panproto.colimit_theories`` call,
    which validates that the merge is consistent and is the categorical
    pushout of the two branches over their shared ancestor.

    This call is the only place in ``didactic`` proper that imports
    ``panproto``. Doing it lazily lets the rest of the package be
    authored and unit-tested without panproto installed.
    """
    import panproto  # noqa: PLC0415

    parents = _model_parents(cls)
    if len(parents) <= 1:
        # single (or no) Model inheritance: the flat spec is correct
        theory = _theory_of_fields(
            cls, cls.__field_specs__, _indexed_context(cls.__field_specs__)
        )
        panproto.typecheck_theory(theory)
        return theory

    # multiple Model inheritance: compute the colimit of the parent
    # theories over their lowest common ancestor in the Model lineage
    theory = _build_colimit_theory(cls, parents)
    panproto.typecheck_theory(theory)
    return theory


def _theory_of_fields(
    cls: type[Model],
    field_specs: Mapping[str, FieldSpec],
    indexed: _IndexedContext,
    *,
    name: str | None = None,
) -> panproto.Theory:
    """Materialise the Theory of ``cls`` restricted to ``field_specs``.

    Parameters
    ----------
    cls
        The model whose primary sort the fields are operations on.
    field_specs
        The fields, keyed by name.
    indexed
        The dependent telescope of ``cls``.
    name
        The Theory's name; defaults to that of the primary sort.

    Returns
    -------
    panproto.Theory
        The Theory, declaring every other model's sort it names.
    """
    import panproto  # noqa: PLC0415

    spec = _spec_of_fields(_schema_kind(cls), field_specs, indexed)
    if name is not None:
        spec["name"] = name
    return panproto.create_theory(_spec_payload(with_external_sorts(spec, field_specs)))


def _model_parents(cls: type[Model]) -> list[type[Model]]:
    """Return ``cls``'s immediate Model bases in declaration order.

    Parameters
    ----------
    cls
        A class to inspect.

    Returns
    -------
    list of type
        Each entry is a Model subclass that ``cls`` directly inherits
        from. The base ``Model`` itself and any non-Model bases are
        excluded.
    """
    from didactic.models._model import BaseModel, Model  # noqa: PLC0415

    return [
        b
        for b in cls.__bases__
        if issubclass(b, Model) and b is not Model and b is not BaseModel
    ]


def _lowest_common_model_ancestor(parents: list[type[Model]]) -> type[Model]:
    """Find the lowest common ancestor of ``parents`` in the Model lineage.

    Parameters
    ----------
    parents
        Two or more Model subclasses.

    Returns
    -------
    type
        The most-derived Model class that appears in every parent's
        MRO. Falls back to [Model][didactic.api.Model] itself if the
        parents share no closer ancestor.
    """
    from didactic.models._model import BaseModel, Model  # noqa: PLC0415

    common = set(parents[0].__mro__)
    for parent in parents[1:]:
        common.intersection_update(parent.__mro__)

    # filter to Model lineage and order by MRO depth (most derived first)
    candidates = [
        c
        for c in parents[0].__mro__
        if c in common and issubclass(c, Model) and c is not BaseModel
    ]
    return candidates[0] if candidates else Model


def _same_emission(
    owner: type[Model], name: str, left: FieldSpec, right: FieldSpec
) -> bool:
    """Whether two specs of one field of ``owner`` emit the same records."""
    kind = _schema_kind(owner)
    unindexed = _IndexedContext((), frozenset(), ())
    return _spec_of_fields(kind, {name: left}, unindexed) == _spec_of_fields(
        kind, {name: right}, unindexed
    )


def _build_colimit_theory(
    cls: type[Model], parents: list[type[Model]]
) -> panproto.Theory:
    """Compute the pushout of the parents' fields over the shared ones.

    Parameters
    ----------
    cls
        The Model subclass with multiple parents.
    parents
        ``cls``'s immediate Model bases (length >= 2).

    Returns
    -------
    panproto.Theory
        The colimit Theory; it has the sorts and operations of the flat
        theory of ``cls``, with panproto's categorical join validated.

    Raises
    ------
    panproto.GatError
        If two parents declare a field at different types, neither has
        it from a common ancestor, and ``cls`` does not redeclare it.

    Notes
    -----
    A field inherited by ``cls`` is an operation on the sort of ``cls``,
    so each parent contributes its fields renamed to that sort: the
    theory of ``cls`` restricted to them. The theories of the ancestor
    and of the parents are then included in one another by name, which
    is what ``panproto.colimit_theories`` joins along.

    An overridden field belongs to no parent's contribution. That is a
    field ``cls`` redeclares, and a field two parents have from a common
    ancestor that differs, in a parent, from the one ``cls`` ends up
    with.

    For more than two parents, the colimit is computed left-to-right,
    over the fields two parents have from a common ancestor.
    """
    import panproto  # noqa: PLC0415

    from didactic.models._meta import read_class_annotations  # noqa: PLC0415

    field_specs = cls.__field_specs__
    indexed = _indexed_context(field_specs)
    redeclared = read_class_annotations(cls).keys()

    ancestral = {
        name
        for left, right in combinations(parents, 2)
        for name in _lowest_common_model_ancestor([left, right]).__field_specs__
    }

    def contribution(parent: type[Model]) -> dict[str, FieldSpec]:
        return {
            name: spec
            for name, spec in parent.__field_specs__.items()
            if name not in redeclared
            and (
                name not in ancestral
                or _same_emission(cls, name, spec, field_specs[name])
            )
        }

    joined = contribution(parents[0])
    accumulator = _theory_of_fields(cls, joined, indexed, name=_schema_kind(parents[0]))

    for parent in parents[1:]:
        fields = contribution(parent)
        shared = {
            name: spec
            for name, spec in fields.items()
            if name in ancestral and name in joined
        }
        accumulator = panproto.colimit_theories(
            accumulator,
            _theory_of_fields(cls, fields, indexed, name=_schema_kind(parent)),
            _theory_of_fields(cls, shared, indexed),
        )
        joined = {**joined, **fields}

    # finally join the fields cls declares: every sort and operation of the
    # accumulated theory is one of the flat theory of cls
    return panproto.colimit_theories(
        accumulator, _theory_of_fields(cls, field_specs, indexed), accumulator
    )


__all__ = [
    "build_theory",
    "build_theory_spec",
]
