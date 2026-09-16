"""Config groups: a directory of fragments per swappable slot.

Rooted at each search root, a group is a directory whose relative path is
the slot's dotted schema path with ``.`` replaced by ``/``; a fragment is
one document in it, named ``<name>.yaml``, ``<name>.yml``,
``<name>.toml`` or ``<name>.json``. A fragment holds the value of the
slot, not a wrapper: ``model/type_encoder/transformer.yaml`` contains
``kind: transformer`` and ``num_heads: 8``, and the engine mounts it
under ``model.type_encoder`` before merging.

Three spellings feed one ordered selection table keyed by slot: the
primary file's ``defaults:`` list, the ``groups=`` argument, and override
strings whose key contains ``/``. A later selection for a slot already in
the table replaces it in place; the whole table is merged, in table
order, above ``base`` and below the primary file body.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from didactic.settings._documents import (
    candidate_paths,
    find_fragment,
    list_stems,
    load_document,
    locate,
)
from didactic.settings._errors import ConfigError, MissingFragmentError
from didactic.settings._provenance import Layer, Origin
from didactic.settings._scalars import parse_override
from didactic.settings._values import nest_override

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from didactic.settings._values import ConfigValue

type Override = str | tuple[str, ConfigValue]
"""One entry of ``compose(overrides=...)``: ``key=value`` text or a typed pair."""


@dataclass(frozen=True, slots=True)
class Selection:
    """One entry of the selection table.

    Parameters
    ----------
    slot
        The dotted schema path the fragment is mounted at, or ``None``
        for a root-mounted ``defaults`` entry, whose document merges at
        the document root.
    name
        The fragment name, or ``None`` when the slot is recorded with no
        selection (``model.type_encoder: null`` in ``defaults``, or
        ``groups={"model.type_encoder": None}``).
    origin
        The origin the fragment's leaves will carry: ``group`` with
        ``slot=name`` for a slot selection, ``defaults`` with the entry
        text for a root-mounted entry. ``path`` is filled in when the
        fragment is loaded.
    """

    slot: str | None
    name: str | None
    origin: Origin


def search_roots(
    primary: Path | str | None, search_path: Sequence[Path | str]
) -> tuple[Path, ...]:
    """Return the search roots: the primary file's parent, then ``search_path``."""
    roots: list[Path] = []
    if primary is not None:
        roots.append(Path(primary).parent)
    roots.extend(Path(entry) for entry in search_path)
    return tuple(roots)


def is_group_override(override: Override) -> bool:
    """Whether an override entry is a group selection (its key contains ``/``)."""
    key = override if isinstance(override, str) else override[0]
    return "/" in key.partition("=")[0]


def split_overrides(
    overrides: Sequence[Override],
) -> tuple[list[tuple[str, str | None]], list[Override]]:
    """Separate group selections from field overrides.

    Returns
    -------
    tuple
        ``(selections, field_overrides)``: the ``(slot, name)`` pairs of
        every override whose key contains ``/``, slot normalised to
        dotted form, in order; and the remaining overrides untouched.

    Raises
    ------
    OverrideSyntaxError
        When a selection string lacks ``=``.
    ConfigError
        When a typed pair with a ``/`` key carries a value that is neither
        a string nor ``None``.
    """
    selections: list[tuple[str, str | None]] = []
    remaining: list[Override] = []
    for override in overrides:
        if not is_group_override(override):
            remaining.append(override)
            continue
        if isinstance(override, str):
            key, text = parse_override(override)
            name: str | None = (
                None if text.strip().lower() in ("", "null", "~") else text
            )
        else:
            key, value = override
            if value is not None and not isinstance(value, str):
                msg = (
                    f"Group selection {key!r} needs a fragment name as a string "
                    f"or null; got {type(value).__name__}"
                )
                raise ConfigError(msg)
            name = value
        selections.append((normalise_slot(key), name))
    return selections, remaining


def normalise_slot(slot: str) -> str:
    """Accept Hydra's ``model/type_encoder`` spelling and return dotted form."""
    return slot.replace("/", ".")


def selection_table(
    defaults: ConfigValue,
    groups: Mapping[str, str | None] | None,
    slash_overrides: Sequence[tuple[str, str | None]],
    *,
    primary: Path | None,
) -> list[Selection]:
    """Build the ordered selection table from the three spellings.

    Parameters
    ----------
    defaults
        The primary file's ``defaults`` value, or ``None`` when absent. A
        string entry is a root-mounted fragment; a one-key mapping
        ``{slot: name}`` (dotted or slash-spelled slot; name a string or
        ``null``) selects a fragment.
    groups
        The ``groups=`` argument, applied in mapping order after the file's
        entries.
    slash_overrides
        ``(slot, name)`` pairs from override strings, applied last.
    primary
        The primary file, named in the errors for malformed entries.

    Raises
    ------
    ConfigError
        When ``defaults`` is not a list, or an entry has the wrong shape.
    """
    table: list[Selection] = []
    if defaults is not None:
        if not isinstance(defaults, list):
            msg = (
                f"'defaults' in {primary} must be a list of file names and "
                f"{{slot: name}} mappings; got {type(defaults).__name__}"
            )
            raise ConfigError(msg)
        for index, entry in enumerate(defaults, start=1):
            table.append(_selection_from_entry(entry, index=index, primary=primary))
    for slot, name in (groups or {}).items():
        _select(table, normalise_slot(slot), name)
    for slot, name in slash_overrides:
        _select(table, slot, name)
    return table


def _selection_from_entry(
    entry: ConfigValue, *, index: int, primary: Path | None
) -> Selection:
    if isinstance(entry, str):
        return Selection(slot=None, name=entry, origin=Origin("defaults", name=entry))
    if isinstance(entry, dict) and len(entry) == 1:
        raw_slot, name = next(iter(entry.items()))
        slot = normalise_slot(raw_slot)
        if name is not None and not isinstance(name, str):
            msg = (
                f"'defaults' entry {slot!r} in {primary} must name a fragment "
                f"as a string or null; got {type(name).__name__}"
            )
            raise ConfigError(msg)
        return _selection(slot, name)
    got = (
        f"a mapping with {len(entry)} keys"
        if isinstance(entry, dict)
        else type(entry).__name__
    )
    msg = (
        f"'defaults' entry {index} in {primary} must be a file name or a "
        f"one-key {{slot: name}} mapping; got {got}"
    )
    raise ConfigError(msg)


def _selection(slot: str, name: str | None) -> Selection:
    return Selection(
        slot=slot, name=name, origin=Origin("group", name=f"{slot}={name}")
    )


def _select(table: list[Selection], slot: str, name: str | None) -> None:
    """Replace the table entry for ``slot`` in place, or append one."""
    replacement = _selection(slot, name)
    for position, existing in enumerate(table):
        if existing.slot == slot:
            table[position] = replacement
            return
    table.append(replacement)


def group_directory(slot: str) -> Path:
    """Return the group directory for a slot, relative to a search root."""
    return Path(*slot.split("."))


def list_names(slot: str, *, roots: Sequence[Path]) -> tuple[str, ...]:
    """Sorted fragment names available for a slot across every root."""
    directory = group_directory(slot)
    return list_stems([root / directory for root in roots])


def find_group_fragment(slot: str, name: str, *, roots: Sequence[Path]) -> Path:
    """Resolve a fragment name for a slot against the search roots.

    Every root holding the group directory is searched in order; the
    earliest root that holds the name wins.

    Raises
    ------
    ConfigError
        When there are no roots at all, or one root holds two files for
        the name.
    MissingFragmentError
        When no root holds the group directory, or none holds the name;
        the message lists the roots searched or every path tried.
    """
    if not roots:
        msg = (
            f"Config group selection '{slot}={name}' needs a config directory; "
            "pass path= or search_path="
        )
        raise ConfigError(msg)
    directory = group_directory(slot)
    holding = [root for root in roots if (root / directory).is_dir()]
    if not holding:
        searched = ", ".join(str(root) for root in roots)
        msg = f"Config group {slot!r} not found; searched: {searched}"
        raise MissingFragmentError(
            msg, group=slot, name=name, tried=tuple(root / directory for root in roots)
        )
    relative = str(directory / name)
    subject = f"Fragment {name!r} of config group {slot!r}"
    found = locate(relative, roots=holding, subject=subject)
    if found is not None:
        return found
    tried = candidate_paths(relative, roots=holding)
    available = list_names(slot, roots=roots)
    msg = (
        f"Config group {slot!r} has no fragment {name!r}; tried: "
        + ", ".join(str(candidate) for candidate in tried)
        + f"; available: {list(available)}"
    )
    raise MissingFragmentError(
        msg, group=slot, name=name, tried=tried, available=available
    )


def load_fragment(selection: Selection, *, roots: Sequence[Path]) -> Layer | None:
    """Load the document a selection names and mount it as a layer.

    Returns ``None`` for a slot recorded with no selection. A root-mounted
    entry's document is the layer as loaded; a slot selection's document
    is wrapped under the slot path, so the merge refuses unknown keys in
    the fragment with the full dotted path and reads its discriminator at
    the slot.

    Raises
    ------
    ConfigError
        When there are no roots, the fragment is ambiguous within a root,
        or its top-level value is not a mapping.
    MissingFragmentError
        When no root holds the fragment.
    """
    if selection.name is None:
        return None
    if selection.slot is None:
        if not roots:
            msg = (
                f"'defaults' entry {selection.name!r} needs a config directory; "
                "pass path= or search_path="
            )
            raise ConfigError(msg)
        file = find_fragment(selection.name, roots=roots)
        document: dict[str, ConfigValue] = load_document(file)
    else:
        file = find_group_fragment(selection.slot, selection.name, roots=roots)
        document = nest_override(selection.slot, load_document(file))
    origin = Origin(selection.origin.kind, name=selection.origin.name, path=str(file))
    return Layer(origin=origin, document=document)


__all__ = [
    "Override",
    "Selection",
    "find_group_fragment",
    "group_directory",
    "is_group_override",
    "list_names",
    "load_fragment",
    "normalise_slot",
    "search_roots",
    "selection_table",
    "split_overrides",
]
