"""The composition pipeline: assemble the ladder, merge, settle, resolve, validate.

Precedence, lowest to highest, with the :class:`~didactic.settings.Origin`
kind each rung stamps:

1. schema defaults (``default``; written by provenance completion and by
   the settle pass for an injected discriminator);
2. the ``base`` mapping (``base``);
3. the selection table: the primary file's ``defaults:`` entries in list
   order, with ``groups=`` and ``slot/path=name`` overrides replacing an
   entry for the same slot in place or appending (``defaults`` for a
   root-mounted fragment, ``group`` for a slot fragment);
4. the primary file body minus ``defaults`` (``file``);
5. the profile (``profile``);
6. the overlays in order (``overlay``);
7. ``Settings.__sources__`` in declaration order (``source``);
8. the overrides in order (``override``): ``key=value`` strings are
   textual, ``(key, value)`` pairs and ``Settings.load(**values)`` are
   typed.

Then the settle pass, interpolation over the whole tree, one
``schema.model_validate(tree)``, and provenance completion from the
validated instance.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, cast
from uuid import UUID

from didactic.settings._documents import find_profile, load_document
from didactic.settings._errors import ConfigError
from didactic.settings._groups import (
    load_fragment,
    search_roots,
    selection_table,
    split_overrides,
)
from didactic.settings._interpolation import resolve_traced
from didactic.settings._merge import check_tree, defaults_view, merge_layer, settle
from didactic.settings._provenance import Layer, Origin, Provenance, complete
from didactic.settings._scalars import parse_override, validate_override_key
from didactic.settings._values import nest_override

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import didactic.api as dx
    from didactic.settings._groups import Override
    from didactic.settings._interpolation import ResolverFn
    from didactic.settings._values import ConfigValue, KeyPath
    from didactic.types._typing import JsonValue


@dataclass(frozen=True, slots=True)
class Composed[M: dx.Model]:
    """The result of a traced composition.

    Parameters
    ----------
    value
        The validated model, with the provenance attached as
        ``__provenance__``.
    tree
        The merged, settled and interpolated document: what
        ``model_validate`` received.
    provenance
        Exactly one origin per leaf of ``value.model_dump_json()``.
    layers
        Every layer applied, lowest precedence first.
    """

    value: M
    tree: dict[str, ConfigValue]
    provenance: Provenance
    layers: tuple[Layer, ...]


def compose[M: dx.Model](
    path: Path | str | None = None,
    *,
    schema: type[M],
    base: Mapping[str, ConfigValue] | None = None,
    groups: Mapping[str, str | None] | None = None,
    profile: str | Mapping[str, ConfigValue] | None = None,
    overlays: Sequence[Path | str | Mapping[str, ConfigValue]] = (),
    overrides: Sequence[Override] = (),
    search_path: Sequence[Path | str] = (),
    resolvers: Mapping[str, ResolverFn] | None = None,
) -> M:
    """Compose a validated model from files, fragments, overlays and overrides.

    Parameters
    ----------
    path
        The primary document. Its ``defaults:`` list selects root
        fragments and config-group fragments; its parent directory is the
        first search root.
    schema
        The model to validate against; every layer is checked against it
        at every depth.
    base
        A mapping merged below everything else.
    groups
        Config-group selections by slot, applied after the file's
        ``defaults:`` entries; ``None`` deselects a slot.
    profile
        A profile name (loaded as ``profiles/<name>`` from the search
        roots) or a mapping used as given.
    overlays
        Documents merged above the profile: file paths or mappings.
    overrides
        ``key=value`` strings (text decoded by the leaf annotation) or
        ``(key, value)`` pairs (typed). A key containing ``/`` selects a
        config group instead.
    search_path
        Directories searched, after the primary file's parent, for
        fragments and profiles.
    resolvers
        Interpolation resolvers consulted before the registry, for this
        call only.

    Returns
    -------
    M
        The validated instance; :func:`~didactic.settings.provenance_of`
        reads its record.

    Raises
    ------
    ConfigError
        For any refusal at any depth: an unknown key, an unknown or
        missing variant, a missing fragment or profile, a malformed
        override, text the leaf annotation cannot read.
    InterpolationError
        For an expression that cannot be resolved.
    didactic.api.ValidationError
        When the resolved tree fails the model's own validation.
    """
    return compose_traced(
        path,
        schema=schema,
        base=base,
        groups=groups,
        profile=profile,
        overlays=overlays,
        overrides=overrides,
        search_path=search_path,
        resolvers=resolvers,
    ).value


def compose_traced[M: dx.Model](
    path: Path | str | None = None,
    *,
    schema: type[M],
    base: Mapping[str, ConfigValue] | None = None,
    groups: Mapping[str, str | None] | None = None,
    profile: str | Mapping[str, ConfigValue] | None = None,
    overlays: Sequence[Path | str | Mapping[str, ConfigValue]] = (),
    overrides: Sequence[Override] = (),
    search_path: Sequence[Path | str] = (),
    resolvers: Mapping[str, ResolverFn] | None = None,
) -> Composed[M]:
    """Compose like :func:`compose` and return the value with its record.

    Parameters are those of :func:`compose`.
    """
    layers = assemble_layers(
        path,
        base=base,
        groups=groups,
        profile=profile,
        overlays=overlays,
        overrides=overrides,
        search_path=search_path,
    )
    return compose_layers(schema=schema, layers=layers, resolvers=resolvers)


def assemble_layers(
    path: Path | str | None = None,
    *,
    base: Mapping[str, ConfigValue] | None = None,
    groups: Mapping[str, str | None] | None = None,
    profile: str | Mapping[str, ConfigValue] | None = None,
    overlays: Sequence[Path | str | Mapping[str, ConfigValue]] = (),
    overrides: Sequence[Override] = (),
    search_path: Sequence[Path | str] = (),
    sources: Sequence[Layer] = (),
) -> list[Layer]:
    """Build the ladder of layers, lowest precedence first.

    ``sources`` are the layers a ``Settings`` class's sources produced;
    they sit above the overlays and below the overrides.

    Raises
    ------
    ConfigError
        When a fragment, profile or file cannot be found or read, or a
        ``defaults`` entry or override is malformed.
    """
    layers: list[Layer] = []
    if base is not None:
        layers.append(Layer(origin=Origin("base"), document=base))
    primary = Path(path) if path is not None else None
    roots = search_roots(primary, search_path)
    document: dict[str, ConfigValue] = (
        load_document(primary) if primary is not None else {}
    )
    defaults = document.pop("defaults", None)
    selections, field_overrides = split_overrides(overrides)
    table = selection_table(defaults, groups, selections, primary=primary)
    for selection in table:
        fragment = load_fragment(selection, roots=roots)
        if fragment is not None:
            layers.append(fragment)
    if primary is not None:
        origin = Origin("file", name=primary.name, path=str(primary))
        layers.append(Layer(origin=origin, document=document))
    if isinstance(profile, str):
        if not roots:
            msg = (
                f"Profile {profile!r} needs a config directory; "
                "pass path= or search_path="
            )
            raise ConfigError(msg)
        file = find_profile(profile, roots=roots)
        origin = Origin("profile", name=profile, path=str(file))
        layers.append(Layer(origin=origin, document=load_document(file)))
    elif profile is not None:
        layers.append(Layer(origin=Origin("profile"), document=profile))
    for index, overlay in enumerate(overlays):
        if isinstance(overlay, str | Path):
            file = Path(overlay)
            origin = Origin("overlay", name=file.name, path=str(file))
            layers.append(Layer(origin=origin, document=load_document(file)))
        else:
            layers.append(
                Layer(origin=Origin("overlay", name=f"#{index}"), document=overlay)
            )
    layers.extend(sources)
    for override in field_overrides:
        layers.append(override_layer(override))
    return layers


def override_layer(override: Override) -> Layer:
    """Turn one override into a layer mounted at its dotted key.

    A ``key=value`` string is a textual layer named by the string; a
    ``(key, value)`` pair is a typed layer named ``key=<json>``.
    """
    if isinstance(override, str):
        key, text = parse_override(override)
        return Layer(
            origin=Origin("override", name=override),
            document=nest_override(key, text),
            textual=True,
        )
    key, value = override
    validate_override_key(key)
    name = f"{key}={json.dumps(value, default=str)}"
    return Layer(
        origin=Origin("override", name=name), document=nest_override(key, value)
    )


def compose_layers[M: dx.Model](
    *,
    schema: type[M],
    layers: Sequence[Layer],
    resolvers: Mapping[str, ResolverFn] | None = None,
) -> Composed[M]:
    """Merge an assembled ladder, settle, interpolate, validate and record.

    Parameters
    ----------
    schema
        The model to validate against.
    layers
        The layers, lowest precedence first.
    resolvers
        Interpolation resolvers consulted before the registry, for this
        call only.

    Raises
    ------
    ConfigError
        For a refusal during the merge, the settle pass or the check of
        the resolved tree, or when the schema declares ``__slots__`` and
        cannot carry the record.
    """
    tree: dict[str, ConfigValue] = {}
    record: dict[KeyPath, Origin] = {}
    for layer in layers:
        tree = merge_layer(tree, layer, schema=schema, provenance=record)
    settle(tree, schema=schema, provenance=record)
    view = defaults_view(tree, schema=schema)
    resolved, expressions = resolve_traced(tree, root=view, resolvers=resolvers)
    for path, text in expressions.items():
        origin = record.get(path)
        record[path] = (
            replace(origin, expression=text)
            if origin is not None
            else Origin("default", expression=text)
        )
    resolved = check_tree(resolved, schema=schema, provenance=record)
    # The JSON path converts the tree's text and list forms (a ``Path`` or
    # ``datetime`` leaf as text, a ``tuple`` field as a list) through each
    # field's ``from_json`` before construction.
    value = schema.model_validate_json(json.dumps(resolved, default=_json_default))
    dumped = cast("dict[str, ConfigValue]", json.loads(value.model_dump_json()))
    provenance = complete(record, dumped)
    attach_provenance(value, provenance)
    return Composed(
        value=value, tree=resolved, provenance=provenance, layers=tuple(layers)
    )


def _json_default(value: object) -> JsonValue:
    """Render a typed value a ``(key, value)`` pair carried into the tree.

    The tree is JSON-shaped, but a typed override may hand the engine a
    ``Path``, a ``datetime``, a ``UUID``, a ``Decimal``, ``bytes`` or an
    enum member; each is rendered the way ``model_dump_json`` renders it.
    """
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, enum.Enum):
        return cast("JsonValue", value.value)
    if isinstance(value, PurePath | UUID | Decimal):
        return str(value)
    msg = f"Object of type {type(value).__name__} is not JSON serializable"
    raise TypeError(msg)


def attach_provenance(value: dx.Model, provenance: Provenance) -> None:
    """Attach the record to a frozen instance as ``__provenance__``.

    Raises
    ------
    ConfigError
        When the model class declares ``__slots__``, which leaves no
        instance dictionary to hold the attribute.
    """
    try:
        object.__setattr__(value, "__provenance__", provenance)
    except AttributeError:
        msg = (
            f"{type(value).__name__} declares __slots__ and cannot carry "
            "provenance; drop the slots declaration or read "
            "compose_traced(...).provenance instead"
        )
        raise ConfigError(msg) from None


__all__ = [
    "Composed",
    "assemble_layers",
    "attach_provenance",
    "compose",
    "compose_layers",
    "compose_traced",
    "override_layer",
]
