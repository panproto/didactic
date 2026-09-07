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
operation rather than changing the sort it names. Class
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

from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    import panproto

    from didactic.fields._fields import FieldSpec
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
    schema_kind = _schema_kind(cls)
    field_specs: dict[str, FieldSpec] = cls.__field_specs__

    sorts: list[dict[str, JsonValue]] = [_primary_sort(schema_kind)]
    ops: list[dict[str, JsonValue]] = []
    # class-level axioms are collected on cls.__class_axioms__ but NOT
    # yet emitted as Theory equations: panproto's `Equation` carries
    # `lhs`/`rhs` Term values, and the surface-syntax -> Term translation
    # is its own piece of work (panproto-Expr-parser hookup).
    eqs: list[dict[str, JsonValue]] = []

    # auxiliary sorts/ops contributed by translations: the Model-ref
    # recursive-alias sum sort, and the TaggedUnion sum sort, which is
    # recomputed here from the live variant registry rather than read
    # from a classify-time snapshot. Deduped by ``name``.
    seen_aux_sorts: set[str] = set()
    seen_aux_ops: set[str] = set()

    for fname, spec in field_specs.items():
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
            ops.append(_edge_accessor(fname, schema_kind, target_sort, optional))
            continue
        if spec.translation.inner_kind == "embed":
            # Embed[T] becomes a containment edge to T's primary sort.
            # The embedded sort itself is not redeclared here; the target
            # Model's own theory carries it. The containment is structural.
            target_sort = _structural_target(spec.translation, "Embed ")
            ops.append(_embed_accessor(fname, schema_kind, target_sort, optional))
            continue
        if spec.translation.inner_kind == "sum":
            # A TaggedUnion root, or a Model-ref recursive alias: the sum
            # sort is already in the auxiliary records above, so the field
            # accessor returns it directly (no per-field constraint sort).
            target_sort = _structural_target(spec.translation, "")
            ops.append(_edge_accessor(fname, schema_kind, target_sort, optional))
            continue
        # constraint sort name follows panproto convention: ParentSort_field
        constraint_sort_name = f"{schema_kind}_{fname}"
        sorts.append(_constraint_sort(constraint_sort_name, spec.translation.sort))
        ops.append(_field_accessor(fname, schema_kind, constraint_sort_name))

    return {
        "name": schema_kind,
        "extends": [],
        "sorts": sorts,
        "ops": ops,
        "eqs": eqs,
        "directed_eqs": [],
        "policies": [],
    }


def _schema_kind(cls: type) -> str:
    """Return ``cls.__schema_kind__``, falling back to the class name."""
    return getattr(cls, "__schema_kind__", cls.__name__)


def _primary_sort(name: str) -> dict[str, JsonValue]:
    """Build the Sort dict for a model's primary vertex.

    Parameters
    ----------
    name
        The sort name; conventionally the class name.
    """
    return {
        "name": name,
        "params": [],
        "kind": "Structural",
        "closure": "Open",
    }


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
    field_name: str, parent_sort: str, target_sort: str, optional: bool = False
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
        "inputs": [["self", parent_sort, "No"]],
        "output": target_sort,
    }
    if optional:
        op["optional"] = True
    return op


def _embed_accessor(
    field_name: str, parent_sort: str, target_sort: str, optional: bool = False
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
        "inputs": [["self", parent_sort, "No"]],
        "output": target_sort,
    }
    if optional:
        op["optional"] = True
    return op


def _field_accessor(
    field_name: str, parent_sort: str, output_sort: str
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
        "inputs": [["self", parent_sort, "No"]],
        "output": output_sort,
    }


# ---------------------------------------------------------------------------
# Runtime (lazy panproto import)
# ---------------------------------------------------------------------------


def build_theory(cls: type) -> panproto.Theory:
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
        colimit (pushout) of the parent theories over their lowest
        common ancestor; otherwise it's the flat theory built from
        ``cls``'s ``__field_specs__``.

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
        spec = build_theory_spec(cls)
        return panproto.create_theory(_spec_payload(spec))

    # multiple Model inheritance: compute the colimit of the parent
    # theories over their lowest common ancestor in the Model lineage
    return _build_colimit_theory(cls, parents)


def _model_parents(cls: type) -> list[type]:
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


def _lowest_common_model_ancestor(parents: list[type]) -> type:
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


def _build_colimit_theory(cls: type, parents: list[type]) -> panproto.Theory:
    """Compute the pushout of two parent theories over their LCA.

    Parameters
    ----------
    cls
        The Model subclass with multiple parents.
    parents
        ``cls``'s immediate Model bases (length >= 2).

    Returns
    -------
    panproto.Theory
        The colimit Theory; equivalent to building ``cls`` as a flat
        theory but with panproto's categorical join validated.

    Notes
    -----
    For more than two parents, the colimit is computed left-to-right.
    The result for ``class D(A, B, C)`` is
    ``colimit(colimit(A, B, lca(A, B)), C, lca(...))``.
    """
    import panproto  # noqa: PLC0415

    accumulator = panproto.create_theory(_spec_payload(build_theory_spec(parents[0])))
    accumulator_cls: type = parents[0]

    for parent in parents[1:]:
        ancestor = _lowest_common_model_ancestor([accumulator_cls, parent])
        ancestor_theory = panproto.create_theory(
            _spec_payload(build_theory_spec(ancestor))
        )
        next_theory = panproto.create_theory(_spec_payload(build_theory_spec(parent)))
        accumulator = panproto.colimit_theories(
            accumulator, next_theory, ancestor_theory
        )
        accumulator_cls = parent

    # finally fold in any cls-only fields by colimiting against the
    # immediate spec of cls; the shared ancestor is the accumulated
    # theory we just built
    cls_theory = panproto.create_theory(_spec_payload(build_theory_spec(cls)))
    return panproto.colimit_theories(accumulator, cls_theory, accumulator)


__all__ = [
    "build_theory",
    "build_theory_spec",
]
