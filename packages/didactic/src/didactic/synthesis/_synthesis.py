"""Synthesise didactic ``Model`` classes from panproto Theory specs.

This module is the faithful inverse of
[build_theory_spec][didactic.theory._theory.build_theory_spec]: it takes a
single Theory spec dict (or a ``panproto.Theory``) and reconstructs a
[Model][didactic.api.Model] subclass whose forward spec round-trips.

Reconstruction strategy
------------------------
The forward path emits, per model:

- one primary ``Structural`` sort named after the model,
- one constraint sort per scalar / container / optional field, named
  ``<Model>_<field>`` and carrying a ``{"Val": <ValueKind>}`` kind,
- one accessor op per field, whose ``output`` is either the field's
  constraint sort (for value fields) or another model's primary sort
  (for ``Ref[T]`` / ``Embed[T]`` edges).

The synthesiser walks the ops in declaration order, dispatching on each
op's ``output``:

- output names a declared ``{"Val": K}`` constraint sort -> a value
  field; the ValueKind is mapped back to a representative Python scalar
  (see :data:`_PY_FOR_VALUE_KIND`),
- output names another sort that is *not* a value constraint -> an edge
  field, reconstructed as ``dx.Ref[Target]``.

Honest limitations (the spec is lossy)
--------------------------------------
The forward Theory spec discards every Python-side distinction that
panproto's ``ValueKind`` enum does not carry:

- Container element types collapse: ``tuple[int, ...]``,
  ``frozenset[str]``, ``dict[str, int]``, ``str | None``, ``Decimal``,
  ``datetime``, ``date``, ``time``, ``UUID`` all encode to
  ``{"Val": "Str"}`` (see ``_theory._VALUE_KIND_FOR_SORT``). The
  synthesiser therefore maps ``Str`` back to a plain ``str``; the
  regenerated model's forward spec is byte-for-byte identical to the
  original, but the Python annotation is *not* recovered.
- ``Ref[T]`` and ``Embed[T]`` produce identical edge ops, so they are
  indistinguishable in the spec. Both are reconstructed as ``Ref[T]``;
  the forward spec of a ``Ref``-regenerated model equals that of the
  ``Embed`` original because both emit a bare edge op.
- Field metadata (descriptions, examples, defaults, validators, axioms,
  aliases, ``nominal`` flags) is not present in the spec and cannot be
  recovered. Every reconstructed field is required (no default) and
  carries no metadata.

Round-trip equality is therefore on the *Theory spec* (structure), never
on Python-side metadata.

Closed sum sorts (``TaggedUnion`` and Model-ref recursive aliases)
-----------------------------------------------------------------
A closed sum sort (``closure: {"Closed": [...]}``) carries one
constructor op per arm. The synthesiser inverts both shapes the forward
path emits:

- A sum sort carrying a ``discriminator`` key comes from a
  ``dx.TaggedUnion`` root. The synthesiser rebuilds the root with that
  discriminator and one variant subclass per constructor, keyed by the
  discriminator value recovered from the constructor name
  (``<Union>_<value>``). Variant payload fields are absent from the
  parent spec, so each rebuilt variant carries only its discriminator
  field; that is enough for the parent's forward spec to round-trip.
- A sum sort without a discriminator comes from a Model-ref recursive
  alias. The synthesiser reads the constructor arms (primitive value
  helpers, container helpers, and Model-sort inputs) and rebuilds an
  equivalent ``type`` alias whose forward spec matches.

The discriminator value's Python type is not recovered: a constructor
name is a string, so a variant's discriminator field is rebuilt as
``Literal["<value>"]`` even when the original pinned a non-string
literal. The constructor name round-trips regardless, so the forward
spec is preserved.

A ``panproto.Theory`` does not carry the ``discriminator`` key (it is
not part of the GAT theory vocabulary, so the native ``to_dict`` drops
it). Reconstructing a ``TaggedUnion`` therefore needs the spec dict from
``build_theory_spec``; ``model_from_theory`` recovers Model-ref aliases
but raises on a discriminator-bearing sum sort whose key the Theory has
dropped.

See Also
--------
didactic.theory._theory.build_theory_spec : the forward path inverted here.
didactic.types._types.classify : the type-classification this undoes.
"""

from __future__ import annotations

import types as _types
from typing import TYPE_CHECKING, Literal, cast

from didactic.fields._refs import Ref
from didactic.fields._unions import TaggedUnion
from didactic.models._model import Model

if TYPE_CHECKING:
    from collections.abc import Iterable

    from didactic.theory._theory import TheorySpec
    from didactic.types._typing import JsonValue


# Inverse of ``_theory._VALUE_KIND_FOR_SORT``. The forward map is
# many-to-one (Str absorbs datetime, decimal, containers, optionals, ...),
# so the inverse picks one representative Python type per ValueKind. ``Str``
# maps to ``str`` because that is the forward path's catch-all sink; a
# regenerated ``str`` field re-encodes to ``{"Val": "Str"}``, so the spec
# round-trips even though the original Python type is not recovered.
_PY_FOR_VALUE_KIND: dict[str, type] = {
    "Str": str,
    "Int": int,
    "Float": float,
    "Bool": bool,
    "Bytes": bytes,
}


def model_from_spec(
    spec: TheorySpec | object,
    *,
    name: str | None = None,
    base: type[Model] = Model,
    registry: dict[str, type[Model]] | None = None,
) -> type[Model]:
    """Synthesise a didactic ``Model`` class from a single Theory spec.

    Parameters
    ----------
    spec
        Either a ``TheorySpec`` dict (the shape produced by
        ``build_theory_spec``) or a ``panproto.Theory``. A Theory is
        detected by the presence of a ``to_dict`` method and converted.
    name
        Class name override. Defaults to the spec's ``name`` field.
    base
        Base class for the synthesised model. Defaults to ``Model``.
        Overridden per-spec when the spec's ``extends`` names a model
        present in ``registry``.
    registry
        Mapping of sort name to already-synthesised ``Model`` classes,
        used to resolve ``extends`` parents and ``Ref`` / ``Embed`` edge
        targets. Edge targets absent from the registry are left as string
        forward references so mutual recursion resolves once every model
        exists. The newly synthesised class is registered under its own
        name before return.

    Returns
    -------
    type[Model]
        The synthesised ``Model`` subclass.

    Raises
    ------
    NotImplementedError
        If the spec carries a discriminator-bearing closed sum sort whose
        ``discriminator`` key has been dropped (the ``panproto.Theory``
        path); pass the ``build_theory_spec`` dict to recover it.

    Notes
    -----
    The reconstruction is faithful at the Theory-spec level only. See the
    module docstring for the recoverable / unrecoverable split.
    """
    spec_dict = _as_spec_dict(spec)
    registry = {} if registry is None else registry

    sort_name = cast("str", spec_dict.get("name") or name or "Synthesised")
    class_name = name or sort_name

    sorts = cast("list[dict[str, JsonValue]]", spec_dict.get("sorts", []))
    ops = cast("list[dict[str, JsonValue]]", spec_dict.get("ops", []))
    extends = cast("list[str]", spec_dict.get("extends", []))

    # index the value-constraint sorts by name so each accessor op can be
    # classified as value-field-vs-edge from its output sort
    value_kinds = _value_constraint_kinds(sorts)

    # invert each closed sum sort into a Python type (TaggedUnion root or
    # Model-ref alias), keyed by sort name. ``constructor_names`` collects
    # the per-arm constructor ops so the field walk skips them: they are
    # introduction forms for the sum, not accessor fields of this model.
    sum_types, constructor_names = _build_sum_types(sorts, ops, registry)

    annotations: dict[str, object] = {}
    for op in ops:
        fname = cast("str", op["name"])
        if fname in constructor_names:
            continue
        output = cast("str", op["output"])
        if output in sum_types:
            annotations[fname] = sum_types[output]
        elif output in value_kinds:
            annotations[fname] = _PY_FOR_VALUE_KIND.get(value_kinds[output], str)
        else:
            # the output is another model's primary sort: an edge field.
            # Ref and Embed are indistinguishable in the spec; reconstruct
            # as Ref. Resolve the target through the registry when present,
            # else leave a string forward reference.
            target = registry.get(output)
            annotations[fname] = Ref[target if target is not None else output]

    bases = _resolve_bases(extends, base, registry)

    namespace: dict[str, object] = {
        "__annotations__": annotations,
        "__module__": __name__,
        "__qualname__": class_name,
        "__doc__": f"Model synthesised from the {sort_name!r} Theory spec.",
    }

    new_cls = cast("type[Model]", type(class_name, bases, namespace))
    # register under the spec's sort name so later models resolve edges /
    # extends against this class
    registry[sort_name] = new_cls
    return new_cls


def models_from_specs(
    specs: Iterable[TheorySpec | object],
    *,
    base: type[Model] = Model,
) -> dict[str, type[Model]]:
    """Synthesise many models, sharing one registry for cross-references.

    Parameters
    ----------
    specs
        An iterable of ``TheorySpec`` dicts or ``panproto.Theory`` objects.
    base
        Base class for models that declare no ``extends`` parent.

    Returns
    -------
    dict[str, type[Model]]
        Mapping of each model's sort name to its synthesised class.

    Notes
    -----
    Specs are topologically ordered by their ``extends`` dependency so a
    parent is always synthesised before its child. ``Ref`` / ``Embed``
    edge targets that form cycles (mutually-referencing models) resolve
    through the shared registry: the first model to reference a not-yet
    synthesised target gets a string forward reference, which didactic's
    metaclass closes once both classes exist.

    Ordering only sequences ``extends`` (inheritance) dependencies, not
    edge dependencies, because edge targets tolerate forward references
    while base classes do not.
    """
    materialised = [_as_spec_dict(s) for s in specs]
    ordered = _topo_sort_by_extends(materialised)

    registry: dict[str, type[Model]] = {}
    for spec_dict in ordered:
        model_from_spec(spec_dict, base=base, registry=registry)
    return registry


def model_from_theory(theory: object, **kwargs: object) -> type[Model]:
    """Synthesise a ``Model`` from a ``panproto.Theory``.

    Parameters
    ----------
    theory
        A ``panproto.Theory`` instance.
    **kwargs
        Forwarded to [model_from_spec][didactic.synthesis.model_from_spec]
        (``name``, ``base``, ``registry``).

    Returns
    -------
    type[Model]
        The synthesised ``Model`` subclass.
    """
    name = cast("str | None", kwargs.pop("name", None))
    base = cast("type[Model]", kwargs.pop("base", Model))
    registry = cast("dict[str, type[Model]] | None", kwargs.pop("registry", None))
    return model_from_spec(theory, name=name, base=base, registry=registry)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _as_spec_dict(spec: TheorySpec | object) -> dict[str, JsonValue]:
    """Coerce a spec argument to a plain dict.

    Accepts either a ``TheorySpec`` mapping or a ``panproto.Theory``
    (detected by a callable ``to_dict`` attribute).
    """
    to_dict = getattr(spec, "to_dict", None)
    if callable(to_dict) and not isinstance(spec, dict):
        return cast("dict[str, JsonValue]", to_dict())
    return cast("dict[str, JsonValue]", spec)


def _value_constraint_kinds(sorts: list[dict[str, JsonValue]]) -> dict[str, str]:
    """Index value-constraint sorts to their ValueKind variant.

    A value-constraint sort is one whose ``kind`` is ``{"Val": K}``.
    Structural sorts (the primary sort and any closed sum sorts) are
    skipped. The returned mapping is keyed by sort name so an accessor op
    can be classified value-field-vs-edge from its ``output``.
    """
    kinds: dict[str, str] = {}
    for sort in sorts:
        kind = sort.get("kind")
        if isinstance(kind, dict) and "Val" in kind:
            kinds[cast("str", sort["name"])] = cast("str", kind["Val"])
    return kinds


# ---------------------------------------------------------------------------
# closed sum sorts (TaggedUnion roots and Model-ref recursive aliases)
# ---------------------------------------------------------------------------

# Inverse of ``_types._PRIMITIVE_TAGS`` (the alias primitive-arm tags). The
# forward path names a primitive arm's value-helper sort
# ``<Alias>__<tag>_value``; the synthesiser maps the tag back to its Python
# type. ``none`` denotes ``NoneType`` (a bare ``None`` arm in the union).
_PY_FOR_PRIMITIVE_TAG: dict[str, object] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "none": None,
}


def _build_sum_types(
    sorts: list[dict[str, JsonValue]],
    ops: list[dict[str, JsonValue]],
    registry: dict[str, type[Model]],
) -> tuple[dict[str, object], set[str]]:
    """Invert every closed sum sort in a spec into a Python type.

    Parameters
    ----------
    sorts
        The spec's sort records.
    ops
        The spec's operation records; the constructor ops for each closed
        sum sort are read here.
    registry
        Shared sort-name to class map. Synthesised ``TaggedUnion`` roots,
        their variants, and Model arms are registered so later models
        resolve edges against the same objects.

    Returns
    -------
    tuple
        ``(sum_types, constructor_names)``. ``sum_types`` maps each closed
        sum sort name to the synthesised Python type (a ``TaggedUnion``
        subclass or a ``type`` alias). ``constructor_names`` is every
        per-arm constructor op name, so the field walk can skip them.
    """
    closed_sums = {cast("str", s["name"]): s for s in sorts if _is_closed_sum(s)}
    ops_by_name = {cast("str", op["name"]): op for op in ops}

    constructor_names: set[str] = set()
    arms_by_sum: dict[str, list[tuple[str, str | None]]] = {}
    for sum_name, sort in closed_sums.items():
        closure = cast("dict[str, JsonValue]", sort["closure"])
        closed = cast("list[str]", closure["Closed"])
        arms: list[tuple[str, str | None]] = []
        for ctor_name in closed:
            constructor_names.add(ctor_name)
            input_sort = _constructor_input_sort(ops_by_name.get(ctor_name))
            arms.append((ctor_name, input_sort))
        arms_by_sum[sum_name] = arms

    sum_types: dict[str, object] = {}
    for sum_name, sort in closed_sums.items():
        arms = arms_by_sum[sum_name]
        if "discriminator" in sort:
            sum_types[sum_name] = _build_tagged_union(
                sum_name, cast("str", sort["discriminator"]), arms, registry
            )
        elif _has_alias_arm(sum_name, arms):
            sum_types[sum_name] = _build_model_ref_alias(sum_name, arms, registry)
        else:
            # A closed sum whose arms are all Model sorts, with no
            # value/container helper, is a TaggedUnion whose discriminator
            # key the carrier dropped (the panproto.Theory path drops
            # didactic-private keys). Without the discriminator field name
            # the union cannot be rebuilt.
            msg = (
                f"closed sum sort {sum_name!r} has no discriminator key and no "
                "value or container arm, so it is a TaggedUnion whose "
                "discriminator was dropped by a panproto.Theory. Synthesise "
                "from the build_theory_spec dict, which preserves it."
            )
            raise NotImplementedError(msg)
    return sum_types, constructor_names


def _has_alias_arm(sum_name: str, arms: list[tuple[str, str | None]]) -> bool:
    """Return True iff any arm is a value or container helper (alias shape).

    A Model-ref alias always carries at least one container arm (its
    self-reference) and may carry primitive value arms; both route through
    ``<sum_name>__...`` helper sorts. A discriminator-bearing union routes
    every arm through a variant's primary sort instead.
    """
    helper_prefix = f"{sum_name}__"
    return any(
        input_sort is not None
        and input_sort.startswith(helper_prefix)
        and input_sort.endswith("_value")
        for input_sort in (arm[1] for arm in arms)
    )


def _is_closed_sum(sort: dict[str, JsonValue]) -> bool:
    """Return True iff ``sort`` is a closed sum sort (``closure`` is ``Closed``)."""
    closure = sort.get("closure")
    return isinstance(closure, dict) and "Closed" in closure


def _constructor_input_sort(op: dict[str, JsonValue] | None) -> str | None:
    """Return a constructor op's single input sort name, or ``None``.

    Constructor ops are unary (one ``(param, sort, implicit)`` input);
    the input sort is the arm's payload (a value-helper sort, a container
    helper, or a Model's primary sort).
    """
    if op is None:
        return None
    inputs = cast("list[list[str]]", op.get("inputs", []))
    if not inputs:
        return None
    return inputs[0][1]


def _build_tagged_union(
    union_name: str,
    discriminator: str,
    arms: list[tuple[str, str | None]],
    registry: dict[str, type[Model]],
) -> type[TaggedUnion]:
    """Rebuild a ``dx.TaggedUnion`` root and its variants from a sum sort.

    Each arm's constructor name is ``<union_name>_<discriminator-value>``
    and its input sort is the variant's primary sort (the variant class
    name). The rebuilt root declares ``discriminator``; each variant
    subclasses the root and pins its discriminator field to the value
    recovered from the constructor name. Variant payload fields are not
    present in this spec, so a variant carries only its discriminator.
    """
    _require_identifier(union_name, "TaggedUnion sort")
    _require_identifier(discriminator, "discriminator field")

    root = cast(
        "type[TaggedUnion]",
        _types.new_class(
            union_name,
            (TaggedUnion,),
            {"discriminator": discriminator},
            lambda ns: ns.update({"__module__": __name__, "__qualname__": union_name}),
        ),
    )
    for ctor_name, payload_sort in arms:
        disc_value = ctor_name.removeprefix(f"{union_name}_")
        variant_name = payload_sort or f"{union_name}_{disc_value}"
        _require_identifier(variant_name, "variant sort")
        annotations = {discriminator: Literal[disc_value]}
        variant = _types.new_class(
            variant_name,
            (root,),
            {},
            lambda ns, _ann=annotations, _name=variant_name: ns.update(
                {
                    "__annotations__": _ann,
                    "__module__": __name__,
                    "__qualname__": _name,
                }
            ),
        )
        registry.setdefault(variant_name, cast("type[Model]", variant))
    registry[union_name] = cast("type[Model]", root)
    return root


def _build_model_ref_alias(
    alias_name: str,
    arms: list[tuple[str, str | None]],
    registry: dict[str, type[Model]],
) -> object:
    """Rebuild a Model-ref recursive ``type`` alias from a sum sort.

    The forward path emits, per arm: a primitive value helper named
    ``<alias>__<tag>_value``, a shared container helper
    ``<alias>__list_value`` / ``<alias>__dict_value`` (constructor name
    ending ``_list`` / ``_tuple`` / ``_dict``), or a Model's primary sort
    directly. The arm payloads of container elements collapse to a string
    helper, so the rebuilt alias references itself in its container arms;
    this reproduces the forward spec exactly while making the alias
    self-referential (the shape ``classify`` requires).
    """
    _require_identifier(alias_name, "alias sort")
    value_prefix = f"{alias_name}__"
    arm_exprs: list[str] = []
    arm_namespace: dict[str, object] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "tuple": tuple,
        "dict": dict,
        "list": list,
    }
    for ctor_name, input_sort in arms:
        if input_sort == f"{alias_name}__dict_value":
            arm_exprs.append(f"dict[str, {alias_name!r}]")
        elif input_sort == f"{alias_name}__list_value":
            if ctor_name.endswith("_tuple"):
                arm_exprs.append(f"tuple[{alias_name!r}, ...]")
            else:
                arm_exprs.append(f"list[{alias_name!r}]")
        elif (
            input_sort is not None
            and input_sort.startswith(value_prefix)
            and input_sort.endswith("_value")
        ):
            tag = input_sort[len(value_prefix) : -len("_value")]
            arm_exprs.append("None" if tag == "none" else _primitive_arm_expr(tag))
        else:
            # Model arm: the input sort is the arm Model's primary sort.
            model_name = input_sort or ctor_name
            _require_identifier(model_name, "Model arm sort")
            arm_namespace[model_name] = registry.get(model_name) or _stub_model(
                model_name, registry
            )
            arm_exprs.append(model_name)

    statement = f"type {alias_name} = " + " | ".join(arm_exprs)
    # ``exec`` builds a genuine PEP 695 alias whose forward references
    # (the self-reference and Model arms) resolve lazily against
    # ``arm_namespace``. Every interpolated name is identifier-checked
    # above, so the statement carries only vetted names.
    exec(statement, arm_namespace)
    return arm_namespace[alias_name]


def _primitive_arm_expr(tag: str) -> str:
    """Return the source expression for a primitive alias arm tag.

    Raises
    ------
    ValueError
        If ``tag`` is not one of the known primitive tags.
    """
    if tag not in _PY_FOR_PRIMITIVE_TAG:
        msg = f"unknown primitive alias arm tag {tag!r}"
        raise ValueError(msg)
    return tag


def _stub_model(name: str, registry: dict[str, type[Model]]) -> type[Model]:
    """Build and register a fieldless ``Model`` to stand in for an arm sort.

    A sum sort's Model arms reference a model by name only; the arm
    model's own fields are absent from this spec. A fieldless stub
    reproduces the arm's constructor op (whose input is the model's
    primary sort) so the forward spec round-trips.
    """
    stub = cast(
        "type[Model]",
        type(
            name,
            (Model,),
            {
                "__annotations__": {},
                "__module__": __name__,
                "__qualname__": name,
                "__doc__": f"Stub Model for the {name!r} sum-sort arm.",
            },
        ),
    )
    registry.setdefault(name, stub)
    return stub


def _require_identifier(name: str, what: str) -> None:
    """Raise ``ValueError`` unless ``name`` is a valid Python identifier.

    The alias reconstructor interpolates sort names into a ``type``
    statement; gating on identifiers keeps the statement to vetted names.
    """
    if not name.isidentifier():
        msg = f"{what} name {name!r} is not a valid Python identifier"
        raise ValueError(msg)


def _resolve_bases(
    extends: list[str],
    base: type[Model],
    registry: dict[str, type[Model]],
) -> tuple[type[Model], ...]:
    """Resolve a spec's ``extends`` names to base classes via the registry.

    Names present in the registry become real base classes (in declared
    order). When ``extends`` resolves to no registered parent, the
    supplied ``base`` is used as the sole base.
    """
    resolved = [registry[name] for name in extends if name in registry]
    if resolved:
        return tuple(resolved)
    return (base,)


def _topo_sort_by_extends(
    specs: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Order specs so each spec's dependencies precede it.

    Dependencies are a spec's ``extends`` parents (a hard dependency:
    a base class must exist before its subclass) and its closed-sum-sort
    Model arms (a soft dependency: ordering them first lets a union
    variant or alias arm resolve to the fully-synthesised arm Model
    rather than a fieldless stub).

    Parameters
    ----------
    specs
        Spec dicts to order.

    Returns
    -------
    list[dict]
        The specs, dependencies first. Names not in the input set are
        skipped (resolved to the default base or a stub at synthesis
        time). Cycles fall back to input order for the remaining specs;
        the edge / stub forward-reference paths close them.
    """
    by_name = {cast("str", s["name"]): s for s in specs}
    ordered: list[dict[str, JsonValue]] = []
    placed: set[str] = set()

    def visit(name: str, stack: frozenset[str]) -> None:
        if name in placed or name not in by_name or name in stack:
            return
        spec = by_name[name]
        for dep in _spec_dependencies(spec):
            visit(dep, stack | {name})
        placed.add(name)
        ordered.append(spec)

    for spec in specs:
        visit(cast("str", spec["name"]), frozenset())
    return ordered


def _spec_dependencies(spec: dict[str, JsonValue]) -> list[str]:
    """Return the sort names a spec should be ordered after.

    These are the spec's ``extends`` parents plus the Model arms of any
    closed sum sort it declares (a sum-arm Model is a constructor op
    input that is neither a value/container helper nor the model's own
    field-constraint sort).
    """
    deps: list[str] = list(cast("list[str]", spec.get("extends", [])))
    sorts = cast("list[dict[str, JsonValue]]", spec.get("sorts", []))
    ops = cast("list[dict[str, JsonValue]]", spec.get("ops", []))
    closed_sums = {cast("str", s["name"]) for s in sorts if _is_closed_sum(s)}
    if not closed_sums:
        return deps
    value_names = set(_value_constraint_kinds(sorts))
    for op in ops:
        if cast("str", op["output"]) not in closed_sums:
            continue
        arm_sort = _constructor_input_sort(op)
        # a Model arm is a constructor input that names a structural sort
        # (not a value/container helper of the sum)
        if (
            arm_sort is not None
            and arm_sort not in value_names
            and not arm_sort.startswith(f"{cast('str', op['output'])}__")
        ):
            deps.append(arm_sort)
    return deps


__all__ = [
    "model_from_spec",
    "model_from_theory",
    "models_from_specs",
]
