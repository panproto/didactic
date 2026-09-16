"""The strict, schema-aware merge with union descent, and the settle pass.

One layer at a time, :func:`merge_layer` walks the layer's document and
the schema side by side. Every key is checked against the model at that
depth; a tagged-union node is checked against the variant its
discriminator selects, and a node with no tag yet is checked against the
fields the registered variants declare. Lists are set wholesale; map keys
are data and their values merge under the map's value type; text from a
textual layer is decoded by the leaf's annotation at the moment it is
written, and a value that arrives typed is checked against the annotation
at the same moment. A string holding a ``${...}`` expression is written
as it is, at a leaf, a list, a map or a model slot, and the resolved
value is checked by :func:`check_tree` afterwards. Every leaf write stamps
the provenance record.

After the last layer, :func:`settle` injects the discriminator a field
default selects into every tagless union node, checks each node's keys
against the variant now known, materialises the defaults that carry
``${...}`` expressions, merges every map slot over its default map, and
leaves every other default to validation.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Final, Union, cast, get_args, get_origin

import didactic.api as dx
from didactic.settings._errors import (
    ConfigError,
    UnknownKeyError,
    UnknownVariantError,
)
from didactic.settings._interpolation import is_whole_expression, mentions_expression
from didactic.settings._provenance import Layer, Origin, origin_under, prune, stamp
from didactic.settings._scalars import (
    admits,
    check_value,
    decode_text,
    parse_scalar,
    render_annotation,
)
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
    discriminator_aliases,
    discriminator_of,
    field_names,
    field_table,
    registered_tags,
    sorted_tags,
    target_of,
    target_of_type,
    variant_for_tag,
    variant_owners,
    variant_tags,
    variants_of,
)
from didactic.settings._values import dotted
from didactic.types import unwrap_annotated

if TYPE_CHECKING:
    from didactic.settings._values import ConfigValue, KeyPath
    from didactic.types._types import TypeForm


class _Missing:
    """Sentinel for an absent discriminator."""


_MISSING: Final = _Missing()

_NULL_TEXT: Final = frozenset({"", "null", "~"})
"""Text a textual layer may write at an optional slot to clear it."""

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
        The mutable provenance record the writes stamp.
    textual
        Whether string values are text to decode by annotation.
    record
        A record to read origins from for messages, when the values
        being merged were written by earlier layers (the settle pass
        merging a map slot over its default); ``None`` reads ``origin``.
    """

    origin: Origin
    prov: dict[KeyPath, Origin]
    textual: bool
    record: Mapping[KeyPath, Origin] | None = None

    def set_by(self, path: KeyPath) -> Origin | None:
        """Return the origin a message names for a value at ``path``."""
        if self.record is None:
            return self.origin
        return origin_under(self.record, path)

    def label(self, path: KeyPath) -> str:
        """Return the ``(set by ...)`` clause for a value at ``path``."""
        origin = self.set_by(path)
        return f"(set by {origin.label})" if origin is not None else "(set by default)"


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
        not declare, and for a computed or derived field name in an
        override or a textual source layer.
    UnknownVariantError
        For a discriminator naming no registered variant, or one that is
        an interpolation.
    ConfigError
        For a value of the wrong shape at a model, union, map or list
        slot, a non-scalar discriminator, or a key two variants declare
        with different types before any tag is set.
    CoercionError
        For text a textual layer supplies that the leaf annotation cannot
        read, or a typed value the annotation does not admit.
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
            if key in dropped:
                if _refuses_computed(ctx):
                    raise _computed_field((model,), key, (*path, key), ctx)
                continue
            if ignore:
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
        return _merge_leaf(value, target=target, path=path, ctx=ctx)
    if isinstance(target, ListOf):
        return _merge_list(value, target=target, path=path, ctx=ctx)
    if value is None or (
        ctx.textual and isinstance(value, str) and value.strip().lower() in _NULL_TEXT
    ):
        if target.optional:
            stamp(ctx.prov, path, None, ctx.origin)
            return None
        raise _wrong_shape(target, path, ctx, "null")
    if (
        isinstance(value, str)
        and not isinstance(target, UnionOf)
        and mentions_expression(value)
    ):
        stamp(ctx.prov, path, value, ctx.origin)
        return value
    inner = ctx
    if ctx.textual and isinstance(value, str) and value.lstrip().startswith("{"):
        value = parse_scalar(value)
        inner = replace(ctx, textual=False)
    if not isinstance(value, Mapping):
        raise _wrong_shape(target, path, ctx, type(value).__name__)
    return _merge_node(existing, value, target=target, path=path, ctx=inner)


def _merge_node(
    existing: ConfigValue,
    value: Mapping[str, ConfigValue],
    *,
    target: Nested | UnionOf | MapOf,
    path: KeyPath,
    ctx: _Ctx,
) -> dict[str, ConfigValue]:
    """Merge a mapping over a model, union or map node."""
    base: Mapping[str, ConfigValue] | None
    if isinstance(existing, Mapping):
        base = existing
    else:
        base = None
        prune(ctx.prov, path)
    if isinstance(target, MapOf):
        result: dict[str, ConfigValue] = dict(base) if base else {}
        for key, entry in value.items():
            result[key] = _merge_value(
                result.get(key), entry, target=target.inner, path=(*path, key), ctx=ctx
            )
        return result
    if isinstance(target, Nested):
        merged = _merge_model(
            base, value, model=target.model, path=path, ctx=ctx, unknown=None
        )
    else:
        merged = _merge_union(base, value, target=target, path=path, ctx=ctx)
    if not merged and base is None:
        # Nothing below the node was recorded, so the node itself carries
        # the layer that created it; a later leaf write drops this entry.
        ctx.prov[path] = ctx.origin
    return merged


def _merge_leaf(
    value: ConfigValue, *, target: Leaf, path: KeyPath, ctx: _Ctx
) -> ConfigValue:
    """Write a leaf, decoding text or checking a typed value first."""
    where = dotted(path)
    if ctx.textual and isinstance(value, str):
        value = decode_text(value, target.annotation, path=where, origin=ctx.origin)
    else:
        check_value(value, target.annotation, path=where, origin=ctx.set_by(path))
    stamp(ctx.prov, path, value, ctx.origin)
    return value


def _merge_list(
    value: ConfigValue, *, target: ListOf, path: KeyPath, ctx: _Ctx
) -> ConfigValue:
    """Write a list wholesale, checking its elements first.

    ``None`` (or null text under a textual layer) is accepted at an
    optional list slot and refused elsewhere.
    """
    if isinstance(value, str):
        if is_whole_expression(value):
            stamp(ctx.prov, path, value, ctx.origin)
            return value
        if ctx.textual:
            value = decode_text(
                value, target.annotation, path=dotted(path), origin=ctx.origin
            )
    if value is None:
        if not target.optional:
            raise _wrong_shape(target, path, ctx, "null")
        stamp(ctx.prov, path, None, ctx.origin)
        return None
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise _wrong_shape(target, path, ctx, _kind(value))
    if isinstance(target.inner, Leaf):
        checked: list[ConfigValue] = list(value)
        check_value(
            checked, target.annotation, path=dotted(path), origin=ctx.set_by(path)
        )
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

    The discriminator is read before any sibling key, under its field
    name or any alias a variant gives it. An explicit tag in the overlay
    or in the tree selects the variant; a field default never does here
    (the settle pass consults it), so composition order does not matter
    except that a later explicit tag replaces an earlier one and drops
    the old variant's private fields.
    """
    root = target.root
    disc = discriminator_of(root)
    disc_path = (*path, disc)
    overlay = _under_field_name(overlay, disc, discriminator_aliases(root))
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
    variant = _variant_for(tag, root, disc_path, ctx.set_by(disc_path))
    if tag_in is not _MISSING and tag_have is not _MISSING and tag_in != tag_have:
        _switch_variant(result, root, tag_have, variant, path=path, ctx=ctx)
    if tag_in is not _MISSING:
        selected_by = ctx.label(disc_path)
    else:
        selected_by = _selected_by(ctx.prov, disc_path)
    unknown = _variant_unknown(root, variant, tag, selected_by, ctx)
    return _merge_model(
        result, overlay, model=variant, path=path, ctx=ctx, unknown=unknown
    )


def _under_field_name(
    overlay: Mapping[str, ConfigValue], disc: str, aliases: frozenset[str]
) -> Mapping[str, ConfigValue]:
    """Return the overlay with a discriminator given by alias keyed by name."""
    if disc in overlay or not aliases:
        return overlay
    for alias in aliases:
        if alias in overlay:
            return {disc if key == alias else key: v for key, v in overlay.items()}
    return overlay


def _check_tag(
    tag: object, root: type[dx.TaggedUnion], disc_path: KeyPath, ctx: _Ctx
) -> object:
    """Refuse an interpolated or non-scalar tag; decode text against the literals."""
    where = dotted(disc_path)
    if isinstance(tag, str) and "${" in tag:
        msg = (
            f"Discriminator {where!r} is the interpolation {tag!r} "
            f"{ctx.label(disc_path)}; a discriminator must be a literal "
            "value; select variants with a config group or an override"
        )
        raise UnknownVariantError(
            msg, path=where, value=tag, registered=registered_tags(root)
        )
    if not isinstance(tag, str | int):
        msg = (
            f"Discriminator {where!r} must be a scalar; "
            f"got {_kind(tag)} {ctx.label(disc_path)}"
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
    where = dotted(disc_path)
    set_by = f" (set by {origin.label})" if origin is not None else ""
    if not variants_of(root):
        msg = (
            f"Unknown variant {where!r} = {tag!r}{set_by}; {root.__name__} "
            "registers no variants; load the plugins that define them before "
            "composing"
        )
        raise UnknownVariantError(msg, path=where, value=tag)
    variant = variant_for_tag(root, tag)
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
    old = variant_for_tag(root, old_tag)
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

    Each key merges under the target the declaring variants agree on
    (a root-declared field counts as declared by every variant, so a
    variant that shadows it with another annotation makes the variants
    disagree); the node keeps no discriminator, and the settle pass
    decides which variant the field default selects.
    """
    variants = variants_of(root)
    declared = all_variant_fields(root)
    root_table = field_table(root)
    dropped = accepted_and_dropped(root)
    for variant in variants.values():
        dropped |= accepted_and_dropped(variant)
    ignore = root.__model_config__.extra == "ignore"
    for key, value in overlay.items():
        owners = declared.get(key)
        root_spec = root_table.get(key)
        if owners:
            keys = {_target_key(target_of(spec)) for _, spec in owners}
            if len(keys) > 1:
                where = dotted((*path, key))
                tags = _and_list(sorted_tags(tag for tag, _ in owners))
                msg = (
                    f"Config key {where!r} is declared by variants {tags} of "
                    f"{root.__name__} with different types; set "
                    f"{dotted((*path, discriminator_of(root)))} in the same or "
                    "an earlier layer"
                )
                raise ConfigError(msg, path=where)
            spec = owners[0][1]
        elif root_spec is not None:
            spec = root_spec
        elif key in dropped:
            if _refuses_computed(ctx):
                raise _computed_field(
                    (root, *variants.values()), key, (*path, key), ctx
                )
            continue
        elif not variants:
            where = dotted((*path, key))
            msg = (
                f"Unknown config key {where!r} {ctx.label((*path, key))}; "
                f"{root.__name__} registers no variants; load the plugins that "
                "define them before composing"
            )
            raise UnknownVariantError(msg, path=where, value=None)
        elif ignore:
            continue
        else:
            raise _no_variant_declares(root, (*path, key), ctx.set_by((*path, key)))
        sub = (*path, spec.name)
        result[spec.name] = _merge_value(
            result.get(spec.name), value, target=target_of(spec), path=sub, ctx=ctx
        )
    return result


def _target_key(target: Target) -> object:
    """Render a hashable identity for agreement between variants' targets."""
    if isinstance(target, Leaf):
        return ("leaf", target.annotation)
    if isinstance(target, Nested):
        return ("nested", target.model, target.optional)
    if isinstance(target, UnionOf):
        return ("union", target.root, target.optional)
    if isinstance(target, MapOf):
        return ("map", _target_key(target.inner), target.optional)
    return ("list", _target_key(target.inner), target.optional)


# -- errors ----------------------------------------------------------------------


def _refuses_computed(ctx: _Ctx) -> bool:
    """Whether the layer may not carry a computed or derived field name.

    A document layer (a file, a mapping, a profile, an overlay, a file
    source) may be a ``model_dump()`` and is allowed to carry such names,
    which are accepted and dropped. An override or a textual source (the
    environment, a dotenv file, the command line) is never a dump, so
    there the name is a user error.
    """
    kind = ctx.origin.kind
    return kind == "override" or (kind == "source" and ctx.textual)


def _computed_field(
    models: tuple[type[dx.Model], ...], key: str, sub: KeyPath, ctx: _Ctx
) -> UnknownKeyError:
    """Build the refusal for a computed or derived field name in an override."""
    where = dotted(sub)
    what = "derived"
    owner = models[0]
    for model in models:
        if key in model.__computed_fields__:
            what, owner = "computed", model
            break
        if key in model.__derived_field_names__:
            owner = model
            break
    msg = (
        f"Config key {where!r} {ctx.label(sub)} is a {what} field of "
        f"{owner.__name__} and cannot be set"
    )
    return UnknownKeyError(
        msg, path=where, allowed=field_names(owner), set_by=ctx.set_by(sub)
    )


def _plain_unknown(model: type[dx.Model], ctx: _Ctx) -> _Unknown:
    def unknown(_key: str, sub: KeyPath) -> ConfigError:
        where = dotted(sub)
        allowed = field_names(model)
        msg = f"Unknown config key {where!r} {ctx.label(sub)}; allowed: {list(allowed)}"
        return UnknownKeyError(msg, path=where, allowed=allowed, set_by=ctx.set_by(sub))

    return unknown


def _variant_unknown(
    root: type[dx.TaggedUnion],
    variant: type[dx.TaggedUnion],
    tag: object,
    selected_by: str,
    ctx: _Ctx,
) -> _Unknown:
    def unknown(key: str, sub: KeyPath) -> ConfigError:
        owners = variant_owners(root, key)
        origin = ctx.set_by(sub)
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
    return _shape_error(target, path, ctx.set_by(path), got)


def _shape_error(
    target: Target, path: KeyPath, origin: Origin | None, got: str
) -> ConfigError:
    where = dotted(path)
    shape = "a list" if isinstance(target, ListOf) else "a mapping"
    set_by = f" (set by {origin.label})" if origin is not None else ""
    msg = (
        f"Config key {where!r} expects {shape} for {_render_target(target)}"
        f"{set_by}; got {got}"
    )
    return ConfigError(msg, path=where)


def _render_target(target: Target) -> str:
    if isinstance(target, Nested):
        return target.model.__name__
    if isinstance(target, UnionOf):
        return target.root.__name__
    return render_annotation(target.annotation)


def _kind(value: object) -> str:
    return "null" if value is None else type(value).__name__


def _and_list(names: tuple[object, ...]) -> str:
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
    resolve against the composed tree, every map slot is merged over its
    default map (so the layers' entries and the default's entries are
    both present, and a layer's entry composes over the default entry of
    the same key), and every other default is left to validation.

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
    _materialise_defaults(node, model, path=path, prov=prov)
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
    ctx = _Ctx(origin=Origin("default"), prov=prov, textual=False, record=prov)
    for key in node:
        if key not in table:
            unknown = _variant_unknown(root, variant, tag, selected_by, ctx)
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


def _materialise_defaults(
    node: dict[str, ConfigValue],
    model: type[dx.Model],
    *,
    path: KeyPath,
    prov: dict[KeyPath, Origin],
) -> None:
    """Write the defaults the tree must carry into a model node.

    A map slot receives its default map: written whole when no layer
    touched the slot, and otherwise as the lowest layer under the entries
    the layers wrote, so a default entry survives a layer that adds
    another key and a layer's entry composes over the default entry of
    the same key (including through a union entry's default tag). Any
    other absent field whose default carries a ``${...}`` expression
    receives the expression leaves (the whole value for a leaf or a list;
    the expression-carrying leaves only, under their paths, for a nested
    model or a default variant), so the expression resolves against the
    composed tree and provenance records it. Every other default stays
    with the model.
    """
    for name, spec in model.__field_specs__.items():
        if spec.is_required:
            continue
        target = target_of(spec)
        if isinstance(target, MapOf):
            default = shape_default(spec.make_default())
            if not isinstance(default, Mapping):
                continue
            if name not in node:
                node[name] = dict(default)
            elif default:
                ctx = _Ctx(
                    origin=Origin("default"), prov={}, textual=False, record=prov
                )
                node[name] = _merge_value(
                    default, node[name], target=target, path=(*path, name), ctx=ctx
                )
            continue
        if name in node:
            continue
        default = shape_default(spec.make_default())
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
    return variant_for_tag(target.root, tag)


# -- the resolved tree ------------------------------------------------------------


def check_tree(
    tree: dict[str, ConfigValue],
    *,
    schema: type[dx.Model],
    provenance: Mapping[KeyPath, Origin],
) -> dict[str, ConfigValue]:
    """Check the resolved tree against the schema and type its resolved text.

    Interpolation may put any value at a leaf, a list, a map or a model
    slot (a resolver result, a pasted subtree, text concatenated around a
    reference), so the checks the merge applied to typed values are run
    once more over the whole tree after resolution. A leaf an expression
    produced as text (``${oc.env:EPOCHS}`` at an ``int`` leaf, a
    ``${...}`` element of a ``tuple[int, ...]`` list) is decoded by the
    leaf's annotation the way a textual layer's text is, in place. A
    union node whose tag names no variant is left to validation, which
    reports it against the field.

    Returns
    -------
    dict
        ``tree`` itself, with resolved text decoded.

    Raises
    ------
    CoercionError
        For a leaf value the annotation does not admit.
    ConfigError
        For a value of the wrong shape at a model, union, map or list
        slot.
    """
    _check_model(tree, schema, (), provenance)
    return tree


def _check_model(
    node: dict[str, ConfigValue],
    model: type[dx.Model],
    path: KeyPath,
    prov: Mapping[KeyPath, Origin],
) -> None:
    table = field_table(model)
    for key, value in list(node.items()):
        spec = table.get(key)
        if spec is not None:
            node[key] = _check_value(value, target_of(spec), (*path, spec.name), prov)


def _check_value(
    value: ConfigValue,
    target: Target,
    path: KeyPath,
    prov: Mapping[KeyPath, Origin],
) -> ConfigValue:
    origin = origin_under(prov, path)
    if isinstance(target, Leaf):
        return _typed(value, target.annotation, path, origin)
    if value is None:
        if not target.optional:
            raise _shape_error(target, path, origin, "null")
        return None
    if isinstance(target, ListOf):
        return _check_list(value, target, path, prov, origin)
    if not isinstance(value, dict):
        raise _shape_error(target, path, origin, _kind(value))
    if isinstance(target, MapOf):
        for key, entry in list(value.items()):
            value[key] = _check_value(entry, target.inner, (*path, key), prov)
    elif isinstance(target, Nested):
        _check_model(value, target.model, path, prov)
    else:
        variant = _view_class(value, target)
        if variant is not None:
            _check_model(value, variant, path, prov)
    return value


def _check_list(
    value: ConfigValue,
    target: ListOf,
    path: KeyPath,
    prov: Mapping[KeyPath, Origin],
    origin: Origin | None,
) -> ConfigValue:
    if not isinstance(value, list):
        raise _shape_error(target, path, origin, _kind(value))
    if isinstance(target.inner, Leaf):
        return _typed(value, target.annotation, path, origin)
    return [
        _check_value(element, target.inner, (*path, f"[{index}]"), prov)
        for index, element in enumerate(value)
    ]


def _typed(
    value: ConfigValue, annotation: object, path: KeyPath, origin: Origin | None
) -> ConfigValue:
    """Check a resolved leaf, decoding what an expression produced.

    Text is decoded by the annotation; a scalar of another type (an
    integer reference substituted into a ``tuple[str, ...]`` element, a
    ``1`` at a ``bool`` leaf) is rendered as text first, the way a
    substring substitution renders it, and decoded the same way.
    """
    where = dotted(path)
    if origin is not None and origin.expression is not None:
        if isinstance(value, list):
            item = _item_annotation(annotation)
            value = [
                _decode_resolved(element, item, where, origin) for element in value
            ]
        else:
            value = _decode_resolved(value, annotation, where, origin)
    check_value(value, annotation, path=where, origin=origin)
    return value


def _decode_resolved(
    value: ConfigValue, annotation: object, where: str, origin: Origin
) -> ConfigValue:
    if isinstance(value, str):
        return decode_text(value, annotation, path=where, origin=origin)
    if isinstance(value, bool | int | float) and not admits(value, annotation):
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        return decode_text(text, annotation, path=where, origin=origin)
    return value


def _item_annotation(annotation: object) -> object:
    """Read the element annotation of a ``tuple[T, ...]`` or ``frozenset[T]``."""
    target = target_of_type(annotation, None)
    if isinstance(target, ListOf):
        return target.inner.annotation if isinstance(target.inner, Leaf) else object
    base = _unwrap(annotation)
    if get_origin(base) in (Union, UnionType):
        members = [m for m in get_args(base) if m is not NoneType]
        if len(members) == 1:
            return _item_annotation(members[0])
    args = get_args(base)
    return args[0] if args else object


def _unwrap(annotation: object) -> object:
    base, _ = unwrap_annotated(cast("TypeForm", annotation))
    return base


__all__ = [
    "check_tree",
    "defaults_view",
    "merge_layer",
    "settle",
    "shape_default",
    "strict_merge",
]
