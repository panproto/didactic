"""Schema targets: what the merge finds behind each field annotation.

The merge walks a document and a model class side by side. At every key
it needs to know whether the annotation names a leaf (a scalar, a
literal, a list set wholesale), a nested model, a tagged-union root, or a
map whose entries carry one of those. :func:`target_of` reads that from a
field's annotation once; the records here are what the merge, the settle
pass, provenance completion and the environment sources dispatch on.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Literal, TypeIs, Union, cast, get_args, get_origin

import didactic.api as dx
from didactic.types import unwrap_annotated

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from didactic.settings._values import KeyPath
    from didactic.types._types import TypeForm


@dataclass(frozen=True, slots=True)
class Leaf:
    """A value written wholesale: a scalar, a literal, an enum, a list.

    Parameters
    ----------
    annotation
        The full annotation, used to decode text from a textual layer.
    spec
        The field spec, or ``None`` for a map entry.
    optional
        Whether the annotation admits ``None``.
    """

    annotation: object
    spec: dx.FieldSpec | None
    optional: bool


@dataclass(frozen=True, slots=True)
class Nested:
    """A plain model: the merge descends into its field table.

    Parameters
    ----------
    model
        The model class.
    spec
        The field spec, or ``None`` for a map entry or the root.
    optional
        Whether the annotation admits ``None``.
    """

    model: type[dx.Model]
    spec: dx.FieldSpec | None
    optional: bool


@dataclass(frozen=True, slots=True)
class UnionOf:
    """A tagged-union root: the discriminator selects the variant to descend.

    Parameters
    ----------
    root
        The union root class; its ``__variants__`` is read live.
    spec
        The field spec, whose default may select a variant at settle, or
        ``None`` for a map entry or list element (no default variant).
    optional
        Whether the annotation admits ``None``.
    """

    root: type[dx.TaggedUnion]
    spec: dx.FieldSpec | None
    optional: bool


@dataclass(frozen=True, slots=True)
class MapOf:
    """A ``dict[str, T]`` field: user keys, entries merged under ``inner``.

    Parameters
    ----------
    inner
        The target of every entry.
    annotation
        The full annotation, for messages and text decoding.
    spec
        The field spec, or ``None`` for a nested map entry.
    optional
        Whether the annotation admits ``None``.
    """

    inner: Target
    annotation: object
    spec: dx.FieldSpec | None
    optional: bool


@dataclass(frozen=True, slots=True)
class ListOf:
    """A ``tuple[T, ...]`` field: replaced wholesale, elements checked.

    Parameters
    ----------
    inner
        The target each dict element is checked against.
    annotation
        The full annotation, for text decoding.
    spec
        The field spec, or ``None`` for a nested list entry.
    optional
        Whether the annotation admits ``None``.
    """

    inner: Target
    annotation: object
    spec: dx.FieldSpec | None
    optional: bool


type Target = Leaf | Nested | UnionOf | MapOf | ListOf
"""What the merge finds behind an annotation."""


def target_of(spec: dx.FieldSpec) -> Target:
    """Return the target of a field."""
    return target_of_type(spec.annotation, spec)


def target_of_type(annotation: object, spec: dx.FieldSpec | None) -> Target:
    """Return the target of an annotation.

    ``Annotated[T, ...]`` (including ``Embed[T]``) unwraps to ``T``; a
    union with ``None`` peels to its one other member and marks the
    target optional; any other union of types is a leaf.
    """
    base = _unwrap(annotation)
    optional = False
    if get_origin(base) in (Union, UnionType):
        members = get_args(base)
        inner = [member for member in members if member is not NoneType]
        optional = len(inner) < len(members)
        if len(inner) != 1:
            return Leaf(annotation=annotation, spec=spec, optional=optional)
        base = _unwrap(inner[0])
    if is_union_root(base):
        return UnionOf(root=base, spec=spec, optional=optional)
    if isinstance(base, type) and issubclass(base, dx.Model):
        return Nested(model=base, spec=spec, optional=optional)
    head = get_origin(base)
    if head is dict:
        return MapOf(
            inner=target_of_type(get_args(base)[1], None),
            annotation=annotation,
            spec=spec,
            optional=optional,
        )
    if head is tuple:
        return ListOf(
            inner=target_of_type(get_args(base)[0], None),
            annotation=annotation,
            spec=spec,
            optional=optional,
        )
    return Leaf(annotation=annotation, spec=spec, optional=optional)


def _unwrap(annotation: object) -> object:
    base, _ = unwrap_annotated(cast("TypeForm", annotation))
    return base


def is_union_root(cls: object) -> TypeIs[type[dx.TaggedUnion]]:
    """Whether ``cls`` is a tagged-union root (not a variant).

    A root is a ``TaggedUnion`` subclass whose own ``__dict__`` sets
    ``__discriminator__``; variants inherit the attribute and are plain
    models to the merge.
    """
    return (
        isinstance(cls, type)
        and issubclass(cls, dx.TaggedUnion)
        and cls.__dict__.get("__discriminator__") is not None
    )


def field_table(model: type[dx.Model]) -> dict[str, dx.FieldSpec]:
    """Field specs keyed by name, with every alias mapping to its spec too.

    A key given by alias is stored under the field name, since
    ``Model.__init__`` accepts field names only.
    """
    table: dict[str, dx.FieldSpec] = dict(model.__field_specs__)
    for spec in model.__field_specs__.values():
        if spec.alias is not None and spec.alias not in table:
            table[spec.alias] = spec
    return table


def field_names(model: type[dx.Model]) -> tuple[str, ...]:
    """Sorted field names of a model (no aliases)."""
    return tuple(sorted(model.__field_specs__))


def accepted_and_dropped(model: type[dx.Model]) -> frozenset[str]:
    """Names a layer may carry that the merge accepts and drops.

    Computed and derived fields appear in ``model_dump`` output, so a
    resolved document composes back without error; they hold no stored
    value, so nothing is written or recorded for them.
    """
    return frozenset(model.__computed_fields__) | frozenset(
        model.__derived_field_names__
    )


def variants_of(root: type[dx.TaggedUnion]) -> dict[object, type[dx.TaggedUnion]]:
    """Read the root's live variant registry, keyed by discriminator value."""
    return cast("dict[object, type[dx.TaggedUnion]]", root.__variants__)


def discriminator_of(root: type[dx.TaggedUnion]) -> str:
    """Read the root's discriminator field name."""
    disc = root.__discriminator__
    if disc is None:
        msg = f"{root.__name__} is not a tagged-union root"
        raise TypeError(msg)
    return disc


def variant_tags(variant: type[dx.TaggedUnion], disc: str) -> tuple[object, ...]:
    """Read the literal values a variant's discriminator field admits, in order."""
    spec = variant.__field_specs__.get(disc)
    if spec is None:
        return ()
    annotation = _unwrap(spec.annotation)
    if get_origin(annotation) is Literal:
        return tuple(cast("tuple[object, ...]", get_args(annotation)))
    return ()


def all_tags(root: type[dx.TaggedUnion]) -> tuple[object, ...]:
    """Every registered discriminator value, in registration order."""
    return tuple(variants_of(root))


def _tag_order(tag: object) -> tuple[str, float | str]:
    if isinstance(tag, bool | int | float):
        return (type(tag).__name__, float(tag))
    return (type(tag).__name__, str(tag))


def sorted_tags(tags: Iterable[object]) -> tuple[object, ...]:
    """Sort discriminator values by type name, then by numeric or text value."""
    return tuple(sorted(tags, key=_tag_order))


def registered_tags(root: type[dx.TaggedUnion]) -> tuple[object, ...]:
    """Every registered discriminator value, live and sorted.

    Messages render the tuple with ``repr``, so a string tag reads
    ``'lstm'`` and an integer tag ``1``, and a typed mismatch (the text
    ``'1'`` against a ``Literal[1]`` union) is visible.
    """
    return sorted_tags(variants_of(root))


def variant_for_tag(
    root: type[dx.TaggedUnion], tag: object
) -> type[dx.TaggedUnion] | None:
    """Find the variant registered under a tag of the same type and value.

    Matching by type as well as value keeps ``True`` from selecting a
    ``Literal[1]`` variant and ``1`` from selecting a ``Literal[True]``
    one, which plain dictionary lookup would allow.
    """
    for candidate, variant in variants_of(root).items():
        if type(candidate) is type(tag) and candidate == tag:
            return variant
    return None


def unique_variants(root: type[dx.TaggedUnion]) -> tuple[type[dx.TaggedUnion], ...]:
    """Every registered variant class once, in registration order."""
    return tuple(dict.fromkeys(variants_of(root).values()))


def primary_tag(root: type[dx.TaggedUnion], variant: type[dx.TaggedUnion]) -> object:
    """Name a variant by its first literal tag, else by its registry key."""
    tags = variant_tags(variant, discriminator_of(root))
    if tags:
        return tags[0]
    for tag, registered in variants_of(root).items():
        if registered is variant:
            return tag
    msg = f"{variant.__name__} is not a registered variant of {root.__name__}"
    raise TypeError(msg)


def discriminator_aliases(root: type[dx.TaggedUnion]) -> frozenset[str]:
    """Every alias the root or a variant gives the discriminator field."""
    disc = discriminator_of(root)
    names: set[str] = set()
    for cls in (root, *unique_variants(root)):
        spec = cls.__field_specs__.get(disc)
        if spec is not None and spec.alias is not None:
            names.add(spec.alias)
    return frozenset(names)


def default_variant(spec: dx.FieldSpec | None) -> type[dx.TaggedUnion] | None:
    """Find the variant a field's default selects, or ``None``.

    ``None`` for a map entry or list element (no spec), for a field whose
    default is ``None`` or ``MISSING``, and for a default that is a bare
    root instance (a root selects no variant).
    """
    if spec is None or spec.is_required:
        return None
    default = spec.make_default()
    if not isinstance(default, dx.TaggedUnion):
        return None
    cls = type(default)
    if is_union_root(cls):
        return None
    return cls


def variant_owners(root: type[dx.TaggedUnion], key: str) -> tuple[object, ...]:
    """Sorted primary tags of the registered variants whose fields include ``key``.

    A variant registered under several literals is listed once, by its
    first literal.
    """
    return sorted_tags(
        primary_tag(root, variant)
        for variant in unique_variants(root)
        if key in field_table(variant)
    )


def all_variant_fields(
    root: type[dx.TaggedUnion],
) -> dict[str, tuple[tuple[object, dx.FieldSpec], ...]]:
    """Every key any variant accepts, mapped to ``(primary tag, spec)`` per variant.

    Root-declared shared fields appear under every variant. Aliases map to
    the same spec as the field name. A variant registered under several
    literals contributes one entry per key.
    """
    table: dict[str, list[tuple[object, dx.FieldSpec]]] = {}
    for variant in unique_variants(root):
        tag = primary_tag(root, variant)
        for key, spec in field_table(variant).items():
            table.setdefault(key, []).append((tag, spec))
    return {key: tuple(owners) for key, owners in table.items()}


def all_field_names(root: type[dx.TaggedUnion]) -> tuple[str, ...]:
    """Sorted union of the root's and every variant's field names."""
    names = set(root.__field_specs__)
    for variant in variants_of(root).values():
        names.update(variant.__field_specs__)
    return tuple(sorted(names))


def settable_paths(schema: type[dx.Model]) -> Iterator[tuple[KeyPath, Target]]:
    """Every path a textual source may set, with its target.

    Yields every leaf path and every model, union and map slot path,
    descending nested models and every registered variant of every union.
    A slot is yielded before the paths below it. Map entries and list
    elements are not enumerable and are not yielded; a map or list slot
    is set whole. A path reached through two variants is yielded once. A
    model reached again inside itself is not descended a second time, so
    a recursive model's inner occurrence is settable only as a whole
    slot.
    """
    seen: set[KeyPath] = set()
    yield from _settable_paths(Nested(schema, None, False), (), seen, ())


def _settable_paths(
    target: Target,
    path: KeyPath,
    seen: set[KeyPath],
    stack: tuple[type, ...],
) -> Iterator[tuple[KeyPath, Target]]:
    if path and path not in seen:
        seen.add(path)
        yield path, target
    if isinstance(target, Nested):
        if target.model in stack:
            return
        for name, spec in target.model.__field_specs__.items():
            yield from _settable_paths(
                target_of(spec), (*path, name), seen, (*stack, target.model)
            )
    elif isinstance(target, UnionOf):
        if target.root in stack:
            return
        for variant in variants_of(target.root).values():
            for name, spec in variant.__field_specs__.items():
                yield from _settable_paths(
                    target_of(spec), (*path, name), seen, (*stack, target.root)
                )


__all__ = [
    "Leaf",
    "ListOf",
    "MapOf",
    "Nested",
    "Target",
    "UnionOf",
    "accepted_and_dropped",
    "all_field_names",
    "all_tags",
    "all_variant_fields",
    "default_variant",
    "discriminator_aliases",
    "discriminator_of",
    "field_names",
    "field_table",
    "is_union_root",
    "primary_tag",
    "registered_tags",
    "settable_paths",
    "sorted_tags",
    "target_of",
    "target_of_type",
    "unique_variants",
    "variant_for_tag",
    "variant_owners",
    "variant_tags",
    "variants_of",
]
