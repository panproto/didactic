"""The strict, schema-aware merge with union descent, and the settle pass.

One layer at a time, :func:`merge_layer` walks the layer's document and
the schema side by side. Every key is checked against the model at that
depth; a tagged-union node is checked against the variant its
discriminator selects, and a node with no tag yet is checked against the
fields the registered variants declare. Lists are set wholesale; map keys
are data and their values merge under the map's value type; text from a
textual layer is decoded by the leaf's annotation at the moment it is
written. Every leaf write stamps the provenance record.

After the last layer, :func:`settle` injects the discriminator a field
default selects into every tagless union node, checks each node's keys
against the variant now known, materialises the defaults that carry
``${...}`` expressions and the map slots no layer touched, and leaves
every other default to validation.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, cast

import didactic.api as dx
from didactic.settings._errors import (
    ConfigError,
    UnknownKeyError,
    UnknownVariantError,
)
from didactic.settings._interpolation import mentions_expression
from didactic.settings._provenance import Layer, Origin, origin_under, prune, stamp
from didactic.settings._scalars import decode_text, parse_scalar
from didactic.settings._schema import (
    Leaf,
    ListOf,
    MapOf,
    Nested,
    Target,
    UnionOf,
    accepted_and_dropped,
    all_field_names,
    all_tags,
    all_variant_fields,
    default_variant,
    discriminator_of,
    field_names,
    field_table,
    registered_tags,
    target_of,
    variant_owners,
    variant_tags,
    variants_of,
)
from didactic.settings._values import dotted

if TYPE_CHECKING:
    from didactic.settings._values import ConfigValue, KeyPath


class _Missing:
    """Sentinel for an absent discriminator."""


_MISSING: Final = _Missing()

type _Unknown = Callable[[str, KeyPath], ConfigError]
"""Builds the error for a key the node's field table does not hold."""


@dataclass(frozen=True, slots=True)
class _Ctx:
    """What every write in one layer shares.

    Parameters
    ----------
    origin
        The layer's origin, stamped on every leaf written.
    prov
        The mutable provenance record.
    textual
        Whether string values are text to decode by annotation.
    """

    origin: Origin
    prov: dict[KeyPath, Origin]
    textual: bool


def merge_layer(
    tree: Mapping[str, ConfigValue],
    layer: Layer,
    *,
    schema: type[dx.Model],
    provenance: dict[KeyPath, Origin],
) -> dict[str, ConfigValue]:
    """Merge one layer over the tree, returning the new tree.

    Parameters
    ----------
    tree
        The tree accumulated so far; it is not modified.
    layer
        The document to merge and the origin its leaves carry.
    schema
        The root model the document is checked against.
    provenance
        The record, updated in place with one entry per leaf written.

    Raises
    ------
    UnknownKeyError
        For a key the model at that depth (or the selected variant) does
        not declare.
    UnknownVariantError
        For a discriminator naming no registered variant, or one that is
        an interpolation.
    ConfigError
        For a value of the wrong shape at a model, union, map or list
        slot, a non-scalar discriminator, or a key two variants declare
        with different types before any tag is set.
    CoercionError
        For text a textual layer supplies that the leaf annotation cannot
        read.
    """
    ctx = _Ctx(origin=layer.origin, prov=provenance, textual=layer.textual)
    return _merge_model(
        tree, layer.document, model=schema, path=(), ctx=ctx, unknown=None
    )


def strict_merge(
    base: Mapping[str, ConfigValue],
    overlay: Mapping[str, ConfigValue],
    *,
    schema: type[dx.Model],
    origin: Origin | None = None,
    provenance: dict[KeyPath, Origin] | None = None,
) -> dict[str, ConfigValue]:
    """Merge one mapping over another under a schema.

    A convenience over :func:`merge_layer` for callers holding two
    documents: the overlay becomes a typed layer with ``origin``
    (``Origin("overlay")`` when omitted) and its leaves are recorded in
    ``provenance`` when one is given.
    """
    layer = Layer(origin=origin or Origin("overlay"), document=overlay)
    record: dict[KeyPath, Origin] = {} if provenance is None else provenance
    return merge_layer(base, layer, schema=schema, provenance=record)


# -- nodes ---------------------------------------------------------------------


def _merge_model(
    existing: Mapping[str, ConfigValue] | None,
    overlay: Mapping[str, ConfigValue],
    *,
    model: type[dx.Model],
    path: KeyPath,
    ctx: _Ctx,
    unknown: _Unknown | None,
) -> dict[str, ConfigValue]:
    """Merge a document over a plain model node (or a selected variant)."""
    result: dict[str, ConfigValue] = dict(existing) if existing else {}
    table = field_table(model)
    dropped = accepted_and_dropped(model)
    ignore = model.__model_config__.extra == "ignore"
    refuse = unknown or _plain_unknown(model, ctx)
    for key, value in overlay.items():
        spec = table.get(key)
        if spec is None:
            if key in dropped or ignore:
                continue
            raise refuse(key, (*path, key))
        sub = (*path, spec.name)
        result[spec.name] = _merge_value(
            result.get(spec.name), value, target=target_of(spec), path=sub, ctx=ctx
        )
    return result


def _merge_value(
    existing: ConfigValue,
    value: ConfigValue,
    *,
    target: Target,
    path: KeyPath,
    ctx: _Ctx,
) -> ConfigValue:
    """Merge one value under its target and return what the tree holds."""
    if isinstance(target, Leaf):
        if ctx.textual and isinstance(value, str):
            value = decode_text(
                value, target.annotation, path=dotted(path), origin=ctx.origin
            )
        stamp(ctx.prov, path, value, ctx.origin)
        return value
    if value is None:
        if target.optional:
            stamp(ctx.prov, path, None, ctx.origin)
            return None
        raise _wrong_shape(target, path, ctx, "null")
    if isinstance(target, ListOf):
        return _merge_list(value, target=target, path=path, ctx=ctx)
    inner = ctx
    if ctx.textual and isinstance(value, str) and value.lstrip().startswith("{"):
        value = parse_scalar(value)
        inner = replace(ctx, textual=False)
    if not isinstance(value, Mapping):
        raise _wrong_shape(target, path, ctx, type(value).__name__)
    base: Mapping[str, ConfigValue] | None
    if isinstance(existing, Mapping):
        base = existing
    else:
        base = None
        prune(ctx.prov, path)
    if isinstance(target, Nested):
        return _merge_model(
            base, value, model=target.model, path=path, ctx=inner, unknown=None
        )
    if isinstance(target, UnionOf):
        return _merge_union(base, value, target=target, path=path, ctx=inner)
    result: dict[str, ConfigValue] = dict(base) if base else {}
    for key, entry in value.items():
        result[key] = _merge_value(
            result.get(key), entry, target=target.inner, path=(*path, key), ctx=inner
        )
    return result


def _merge_list(
    value: ConfigValue, *, target: ListOf, path: KeyPath, ctx: _Ctx
) -> ConfigValue:
    """Write a list wholesale, checking model-shaped elements first."""
    if ctx.textual and isinstance(value, str):
        value = decode_text(
            value, target.annotation, path=dotted(path), origin=ctx.origin
        )
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise _wrong_shape(target, path, ctx, type(value).__name__)
    if isinstance(target.inner, Leaf):
        checked: list[ConfigValue] = list(value)
    else:
        scratch = replace(ctx, prov={})
        checked = [
            _merge_value(
                None,
                element,
                target=target.inner,
                path=(*path, f"[{index}]"),
                ctx=scratch,
            )
            if isinstance(element, Mapping)
            else element
            for index, element in enumerate(value)
        ]
    stamp(ctx.prov, path, checked, ctx.origin)
    return checked


def _merge_union(
    existing: Mapping[str, ConfigValue] | None,
    overlay: Mapping[str, ConfigValue],
    *,
    target: UnionOf,
    path: KeyPath,
    ctx: _Ctx,
) -> dict[str, ConfigValue]:
    """Merge a document over a tagged-union node.

    The discriminator is read before any sibling key. An explicit tag in
    the overlay or in the tree selects the variant; a field default never
    does here (the settle pass consults it), so composition order does
    not matter except that a later explicit tag replaces an earlier one
    and drops the old variant's private fields.
    """
    root = target.root
    disc = discriminator_of(root)
    disc_path = (*path, disc)
    tag_in: object = overlay.get(disc, _MISSING)
    if tag_in is not _MISSING:
        tag_in = _check_tag(tag_in, root, disc_path, ctx)
    tag_have: object = (
        existing.get(disc, _MISSING) if existing is not None else _MISSING
    )
    tag = tag_in if tag_in is not _MISSING else tag_have
    result: dict[str, ConfigValue] = dict(existing) if existing else {}
    if tag is _MISSING:
        return _merge_provisional(result, overlay, root=root, path=path, ctx=ctx)
    variant = _variant_for(tag, root, disc_path, ctx.origin)
    if tag_in is not _MISSING and tag_have is not _MISSING and tag_in != tag_have:
        _switch_variant(result, root, tag_have, variant, path=path, ctx=ctx)
    if tag_in is not _MISSING:
        selected_by = f"(set by {ctx.origin.label})"
    else:
        selected_by = _selected_by(ctx.prov, disc_path)
    unknown = _variant_unknown(root, variant, str(tag), selected_by, ctx.origin)
    return _merge_model(
        result, overlay, model=variant, path=path, ctx=ctx, unknown=unknown
    )


def _check_tag(
    tag: object, root: type[dx.TaggedUnion], disc_path: KeyPath, ctx: _Ctx
) -> object:
    """Refuse an interpolated or non-scalar tag; decode text against the literals."""
    where = dotted(disc_path)
    if isinstance(tag, str) and "${" in tag:
        msg = (
            f"Discriminator {where!r} is the interpolation {tag!r} "
            f"(set by {ctx.origin.label}); a discriminator must be a literal "
            "value; select variants with a config group or an override"
        )
        raise UnknownVariantError(
            msg, path=where, value=tag, registered=registered_tags(root)
        )
    if not isinstance(tag, str | int):
        msg = (
            f"Discriminator {where!r} must be a scalar; "
            f"got {_kind(tag)} (set by {ctx.origin.label})"
        )
        raise ConfigError(msg, path=where)
    if ctx.textual and isinstance(tag, str):
        stripped = tag.strip()
        for candidate in all_tags(root):
            if str(candidate) == stripped or (
                isinstance(candidate, bool)
                and str(candidate).lower() == stripped.lower()
            ):
                return candidate
    return tag


def _variant_for(
    tag: object, root: type[dx.TaggedUnion], disc_path: KeyPath, origin: Origin | None
) -> type[dx.TaggedUnion]:
    """Look up the registered variant for a tag, or raise naming the registry."""
    variants = variants_of(root)
    where = dotted(disc_path)
    set_by = f" (set by {origin.label})" if origin is not None else ""
    if not variants:
        msg = (
            f"Unknown variant {where!r} = {tag!r}{set_by}; {root.__name__} "
            "registers no variants; load the plugins that define them before "
            "composing"
        )
        raise UnknownVariantError(msg, path=where, value=tag)
    variant = variants.get(tag)
    if variant is None:
        msg = (
            f"Unknown variant {where!r} = {tag!r}{set_by}; "
            f"{root.__name__} registers: {list(registered_tags(root))}"
        )
        raise UnknownVariantError(
            msg, path=where, value=tag, registered=registered_tags(root)
        )
    return variant


def _switch_variant(
    result: dict[str, ConfigValue],
    root: type[dx.TaggedUnion],
    old_tag: object,
    variant: type[dx.TaggedUnion],
    *,
    path: KeyPath,
    ctx: _Ctx,
) -> None:
    """Drop the old variant's private fields when a later layer re-tags."""
    old = variants_of(root).get(old_tag)
    if old is None:
        return
    kept = set(root.__field_specs__) | set(variant.__field_specs__)
    for name in list(result):
        if name in old.__field_specs__ and name not in kept:
            del result[name]
            prune(ctx.prov, (*path, name))


def _merge_provisional(
    result: dict[str, ConfigValue],
    overlay: Mapping[str, ConfigValue],
    *,
    root: type[dx.TaggedUnion],
    path: KeyPath,
    ctx: _Ctx,
) -> dict[str, ConfigValue]:
    """Merge over a union node that no layer has tagged yet.

    Each key merges under the target the declaring variants agree on;
    the node keeps no discriminator, and the settle pass decides which
    variant the field default selects.
    """
    variants = variants_of(root)
    declared = all_variant_fields(root)
    root_table = field_table(root)
    dropped = accepted_and_dropped(root)
    for variant in variants.values():
        dropped |= accepted_and_dropped(variant)
    ignore = root.__model_config__.extra == "ignore"
    for key, value in overlay.items():
        spec = root_table.get(key)
        if spec is not None:
            target = target_of(spec)
            name = spec.name
        elif key in dropped:
            continue
        elif not variants:
            where = dotted((*path, key))
            msg = (
                f"Unknown config key {where!r} (set by {ctx.origin.label}); "
                f"{root.__name__} registers no variants; load the plugins that "
                "define them before composing"
            )
            raise UnknownVariantError(msg, path=where, value=None)
        else:
            owners = declared.get(key)
            if owners is None:
                if ignore:
                    continue
                raise _no_variant_declares(root, (*path, key), ctx.origin)
            keys = {_target_key(target_of(spec)) for _, spec in owners}
            if len(keys) > 1:
                where = dotted((*path, key))
                tags = _and_list(sorted(tag for tag, _ in owners))
                msg = (
                    f"Config key {where!r} is declared by variants {tags} of "
                    f"{root.__name__} with different types; set "
                    f"{dotted((*path, discriminator_of(root)))} in the same or "
                    "an earlier layer"
                )
                raise ConfigError(msg, path=where)
            target = target_of(owners[0][1])
            name = owners[0][1].name
        sub = (*path, name)
        result[name] = _merge_value(
            result.get(name), value, target=target, path=sub, ctx=ctx
        )
    return result


def _target_key(target: Target) -> object:
    """Render a hashable identity for agreement between variants' targets."""
    if isinstance(target, Leaf):
        return ("leaf", target.annotation)
    if isinstance(target, Nested):
        return ("nested", target.model)
    if isinstance(target, UnionOf):
        return ("union", target.root)
    if isinstance(target, MapOf):
        return ("map", _target_key(target.inner))
    return ("list", _target_key(target.inner))


# -- errors ----------------------------------------------------------------------


def _plain_unknown(model: type[dx.Model], ctx: _Ctx) -> _Unknown:
    def unknown(_key: str, sub: KeyPath) -> ConfigError:
        where = dotted(sub)
        allowed = field_names(model)
        msg = (
            f"Unknown config key {where!r} (set by {ctx.origin.label}); "
            f"allowed: {list(allowed)}"
        )
        return UnknownKeyError(msg, path=where, allowed=allowed, set_by=ctx.origin)

    return unknown


def _variant_unknown(
    root: type[dx.TaggedUnion],
    variant: type[dx.TaggedUnion],
    tag: str,
    selected_by: str,
    origin: Origin | None,
) -> _Unknown:
    def unknown(key: str, sub: KeyPath) -> ConfigError:
        owners = variant_owners(root, key)
        if not owners:
            return _no_variant_declares(root, sub, origin)
        where = dotted(sub)
        set_by = f" (set by {origin.label})" if origin is not None else ""
        plural = "variants" if len(owners) > 1 else "variant"
        names = ", ".join(repr(owner) for owner in owners)
        msg = (
            f"Unknown config key {where!r}{set_by}: variant {tag!r} of "
            f"{root.__name__} {selected_by} has no field {key!r}; "
            f"it belongs to {plural} {names}"
        )
        return UnknownKeyError(
            msg,
            path=where,
            allowed=field_names(variant),
            declared_by=owners,
            set_by=origin,
        )

    return unknown


def _no_variant_declares(
    root: type[dx.TaggedUnion], sub: KeyPath, origin: Origin | None
) -> UnknownKeyError:
    where = dotted(sub)
    set_by = f" (set by {origin.label})" if origin is not None else ""
    allowed = all_field_names(root)
    msg = (
        f"Unknown config key {where!r}{set_by}; no variant of {root.__name__} "
        f"declares it; allowed: {list(allowed)}"
    )
    return UnknownKeyError(msg, path=where, allowed=allowed, set_by=origin)


def _wrong_shape(target: Target, path: KeyPath, ctx: _Ctx, got: str) -> ConfigError:
    where = dotted(path)
    shape = "a list" if isinstance(target, ListOf) else "a mapping"
    msg = (
        f"Config key {where!r} expects {shape} for {_render_target(target)} "
        f"(set by {ctx.origin.label}); got {got}"
    )
    return ConfigError(msg, path=where)


def _render_target(target: Target) -> str:
    if isinstance(target, Nested):
        return target.model.__name__
    if isinstance(target, UnionOf):
        return target.root.__name__
    return _render_annotation(target.annotation)


def _render_annotation(annotation: object) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    return repr(annotation).replace("typing.", "")


def _kind(value: object) -> str:
    return "null" if value is None else type(value).__name__


def _and_list(names: list[str]) -> str:
    quoted = [repr(name) for name in names]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def _selected_by(prov: Mapping[KeyPath, Origin], disc_path: KeyPath) -> str:
    origin = prov.get(disc_path)
    if origin is None or origin.kind == "default":
        return "(selected by default)"
    return f"(set by {origin.label})"


# -- settle --------------------------------------------------------------------------


def settle(
    tree: dict[str, ConfigValue],
    *,
    schema: type[dx.Model],
    provenance: dict[KeyPath, Origin],
) -> None:
    """Finish the merged tree in place before interpolation.

    At every union node with no discriminator, the enclosing field's
    default selects the variant and its first tag is injected with
    ``Origin("default")``; a node whose field has no default variant (an
    optional slot left ``None``, a map entry, a list element, a default
    that is a bare root instance) is refused. Every key of the node is
    then checked against the selected variant. At every model node the
    defaults that carry ``${...}`` expressions are materialised so they
    resolve against the composed tree, and every map slot no layer
    touched receives its default map; every other default is left to
    validation.

    Raises
    ------
    ConfigError
        When a union node selects no variant.
    UnknownKeyError
        When a key merged before the tag was known belongs to another
        variant.
    """
    _settle_model(tree, model=schema, path=(), prov=provenance)


def _settle_model(
    node: dict[str, ConfigValue],
    *,
    model: type[dx.Model],
    path: KeyPath,
    prov: dict[KeyPath, Origin],
) -> None:
    _materialise_defaults(node, model)
    specs = model.__field_specs__
    for name, value in list(node.items()):
        spec = specs.get(name)
        if spec is not None:
            _settle_value(value, target_of(spec), (*path, name), prov)


def _settle_value(
    value: ConfigValue, target: Target, path: KeyPath, prov: dict[KeyPath, Origin]
) -> None:
    if isinstance(target, ListOf):
        if isinstance(value, list):
            for index, element in enumerate(value):
                _settle_value(element, target.inner, (*path, f"[{index}]"), prov)
        return
    if not isinstance(value, dict):
        return
    if isinstance(target, Nested):
        _settle_model(value, model=target.model, path=path, prov=prov)
    elif isinstance(target, UnionOf):
        _settle_union(value, target=target, path=path, prov=prov)
    elif isinstance(target, MapOf):
        for key, entry in value.items():
            _settle_value(entry, target.inner, (*path, key), prov)


def _settle_union(
    node: dict[str, ConfigValue],
    *,
    target: UnionOf,
    path: KeyPath,
    prov: dict[KeyPath, Origin],
) -> None:
    root = target.root
    disc = discriminator_of(root)
    disc_path = (*path, disc)
    tag: object = node.get(disc, _MISSING)
    if tag is _MISSING:
        variant = default_variant(target.spec)
        tags = variant_tags(variant, disc) if variant is not None else ()
        if variant is None or not tags:
            raise _selects_no_variant(root, path, disc_path, prov)
        tag = tags[0]
        node[disc] = cast("ConfigValue", tag)
        prov[disc_path] = Origin("default")
        selected_by = "(selected by default)"
    else:
        variant = _variant_for(tag, root, disc_path, prov.get(disc_path))
        selected_by = _selected_by(prov, disc_path)
    table = field_table(variant)
    for key in node:
        if key not in table:
            set_by = origin_under(prov, (*path, key))
            unknown = _variant_unknown(root, variant, str(tag), selected_by, set_by)
            raise unknown(key, (*path, key))
    _settle_model(node, model=variant, path=path, prov=prov)


def _selects_no_variant(
    root: type[dx.TaggedUnion],
    path: KeyPath,
    disc_path: KeyPath,
    prov: Mapping[KeyPath, Origin],
) -> ConfigError:
    where = dotted(path)
    origin = origin_under(prov, path)
    set_by = f" (set by {origin.label})" if origin is not None else ""
    if not variants_of(root):
        msg = (
            f"Config key {where!r} selects no variant of {root.__name__}{set_by}; "
            f"{root.__name__} registers no variants; load the plugins that define "
            "them before composing"
        )
    else:
        msg = (
            f"Config key {where!r} selects no variant of {root.__name__}{set_by}: "
            f"set {dotted(disc_path)} to one of {list(registered_tags(root))}"
        )
    return ConfigError(msg, path=where)


# -- defaults ---------------------------------------------------------------------


def _materialise_defaults(node: dict[str, ConfigValue], model: type[dx.Model]) -> None:
    """Write the defaults the tree must carry into a model node.

    A map slot no layer touched receives its default map, since layers
    contribute map entries key by key. Any other absent field whose
    default carries a ``${...}`` expression receives the expression
    leaves (the whole value for a leaf or a list; the expression-carrying
    leaves only, under their paths, for a nested model or a default
    variant), so the expression resolves against the composed tree and
    provenance records it. Every other default stays with the model.
    """
    for name, spec in model.__field_specs__.items():
        if name in node or spec.is_required:
            continue
        default = shape_default(spec.make_default())
        target = target_of(spec)
        if isinstance(target, MapOf):
            if isinstance(default, Mapping):
                node[name] = dict(default)
            continue
        if not mentions_expression(default):
            continue
        if isinstance(target, Nested | UnionOf) and isinstance(default, Mapping):
            node[name] = _expression_leaves(default)
        else:
            node[name] = default


def _expression_leaves(document: Mapping[str, ConfigValue]) -> dict[str, ConfigValue]:
    """Keep only the expression-carrying leaves of a document, under their paths."""
    out: dict[str, ConfigValue] = {}
    for key, value in document.items():
        if isinstance(value, Mapping) and value:
            inner = _expression_leaves(value)
            if inner:
                out[key] = inner
        elif mentions_expression(value):
            out[key] = value
    return out


def shape_default(value: object) -> ConfigValue:
    """Render a field default in tree shape.

    Model instances become dicts over their stored fields (computed and
    derived fields are not stored), tuples and frozensets become lists,
    mappings become dicts, enum members become their values, and every
    other value is kept as it is.
    """
    if isinstance(value, dx.Model):
        return {
            name: shape_default(getattr(value, name))
            for name in type(value).__field_specs__
        }
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): shape_default(entry) for key, entry in mapping.items()}
    if isinstance(value, tuple | list | frozenset | set):
        items = cast(
            "tuple[object, ...] | list[object] | frozenset[object] | set[object]", value
        )
        return [shape_default(item) for item in items]
    if isinstance(value, enum.Enum):
        return cast("ConfigValue", value.value)
    return cast("ConfigValue", value)


def defaults_view(
    tree: Mapping[str, ConfigValue], *, schema: type[dx.Model]
) -> dict[str, ConfigValue]:
    """Back the tree with the schema's defaults, for interpolation lookups.

    Every field absent from a model node is filled from its default, so a
    reference such as ``${trainer.out_dir}`` reads the model's default
    when no layer set the field. The view is read only; the resolved
    document is the tree itself.
    """
    return _view_model(tree, schema)


def _view_model(
    node: Mapping[str, ConfigValue], model: type[dx.Model]
) -> dict[str, ConfigValue]:
    out: dict[str, ConfigValue] = {}
    for name, spec in model.__field_specs__.items():
        if name in node:
            out[name] = _view_value(node[name], target_of(spec))
        elif not spec.is_required:
            out[name] = shape_default(spec.make_default())
    for key, value in node.items():
        if key not in out:
            out[key] = value
    return out


def _view_value(value: ConfigValue, target: Target) -> ConfigValue:
    if isinstance(target, ListOf) and isinstance(value, list):
        return [_view_value(element, target.inner) for element in value]
    if not isinstance(value, Mapping) or isinstance(target, Leaf | ListOf):
        return value
    if isinstance(target, MapOf):
        return {key: _view_value(entry, target.inner) for key, entry in value.items()}
    model = _view_class(value, target)
    return _view_model(value, model) if model is not None else dict(value)


def _view_class(
    value: Mapping[str, ConfigValue], target: Nested | UnionOf
) -> type[dx.Model] | None:
    if isinstance(target, Nested):
        return target.model
    tag: object = value.get(discriminator_of(target.root))
    if not isinstance(tag, str | int):
        return None
    return variants_of(target.root).get(tag)


__all__ = [
    "defaults_view",
    "merge_layer",
    "settle",
    "shape_default",
    "strict_merge",
]
