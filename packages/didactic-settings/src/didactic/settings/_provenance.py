"""Origin records, the layer record that carries them, and the read API.

An :class:`Origin` says which rung of the precedence ladder wrote a
value; a :class:`Layer` is one document tagged with the origin every leaf
it sets will carry; a :class:`Provenance` is the finished record, one
origin per leaf of the validated model.

The leaf definition is the one :func:`~didactic.settings._values.leaves`
implements: a scalar or ``None``, a whole list, an empty dict, and every
leaf reached by descending a non-empty dict. A list is one leaf because
``tuple[T, ...]`` fields are set wholesale by whichever layer wrote them
last; elements are checked against the schema but not attributed
individually, so provenance stops at the list boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from didactic.settings._errors import ConfigError
from didactic.settings._values import dotted, leaves

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx
    from didactic.settings._values import ConfigValue, KeyPath

type OriginKind = Literal[
    "default",
    "base",
    "group",
    "defaults",
    "file",
    "profile",
    "overlay",
    "source",
    "override",
]
"""The closed set of precedence rungs, lowest first.

``default`` is written only by provenance completion and by the settle
pass for an injected discriminator; the others name the layer kinds
``compose`` and ``Settings.load`` apply.
"""


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a leaf's value came from.

    Parameters
    ----------
    kind
        The precedence rung.
    name
        What within the rung: the profile name, ``slot=name`` for a group
        fragment, the ``defaults`` entry text for a root fragment, the
        override text, the file basename, a settings source's name, or
        ``#<index>`` for an in-process overlay mapping. Empty when the
        rung has one anonymous member (``default``, ``base``, a mapping
        profile).
    path
        The on-disk file the value was read from, for file-backed layers.
    expression
        The leaf's source text when it contained ``${...}``; the value
        recorded on the tree is the resolved one.
    """

    kind: OriginKind
    name: str = ""
    path: str | None = None
    expression: str | None = None

    @property
    def label(self) -> str:
        """``kind`` when ``name`` is empty, else ``kind:name``."""
        return self.kind if not self.name else f"{self.kind}:{self.name}"


@dataclass(frozen=True, slots=True)
class Layer:
    """One document to merge, tagged with its origin.

    Parameters
    ----------
    origin
        The origin every leaf the document sets will carry.
    document
        The nested document, already mounted at the root (a group
        fragment is wrapped under its slot path before it becomes a
        layer).
    textual
        Whether string leaves are text to decode by the leaf's annotation
        before the write (environment variables, dotenv lines, CLI
        arguments, ``key=value`` override strings) rather than typed
        values.
    """

    origin: Origin
    document: Mapping[str, ConfigValue]
    textual: bool = False


class Provenance(Mapping[str, Origin]):
    """Which layer wrote each leaf of a composed model.

    An immutable mapping from dotted leaf path to :class:`Origin` that
    iterates in sorted path order and compares by value, so two
    compositions from the same layers give equal records. It covers
    exactly the leaves of ``value.model_dump_json()``: every leaf no layer
    wrote is labelled ``default``. Map keys are recorded verbatim as path
    segments, so a key containing ``.`` makes its path ambiguous. A list
    is one leaf: the elements of a ``tuple[T, ...]`` field are checked
    against the schema but not attributed individually, so the record
    stops at the list boundary.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[str, Origin]) -> None:
        self._entries: dict[str, Origin] = dict(sorted(entries.items()))

    def __getitem__(self, path: str) -> Origin:
        return self._entries[path]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"Provenance({self._entries!r})"

    @property
    def paths(self) -> tuple[str, ...]:
        """Every recorded leaf path, sorted."""
        return tuple(self._entries)

    def source_of(self, path: str, /) -> Origin:
        """Return the origin of one leaf.

        Raises
        ------
        ConfigError
            When no leaf has that path; the message lists the leaves.
        """
        try:
            return self._entries[path]
        except KeyError:
            msg = f"No provenance recorded for {path!r}; leaves: " + ", ".join(
                self._entries
            )
            raise ConfigError(msg, path=path) from None

    def under(self, prefix: str) -> Provenance:
        """Return the entries at or below a dotted prefix, keys kept absolute."""
        return Provenance(
            {
                path: origin
                for path, origin in self._entries.items()
                if path == prefix or path.startswith(prefix + ".")
            }
        )

    def by_layer(self) -> dict[str, tuple[str, ...]]:
        """Group the leaf paths by ``Origin.label``.

        The answer to "what did the profile change": each label maps to
        the sorted paths it wrote.
        """
        groups: dict[str, list[str]] = {}
        for path, origin in self._entries.items():
            groups.setdefault(origin.label, []).append(path)
        return {label: tuple(paths) for label, paths in groups.items()}

    def to_dict(self) -> dict[str, dict[str, str | None]]:
        """Render the record as JSON-shaped dicts, for a sidecar file."""
        return {
            path: {
                "kind": origin.kind,
                "name": origin.name,
                "path": origin.path,
                "expression": origin.expression,
            }
            for path, origin in self._entries.items()
        }


def provenance_of(model: dx.Model) -> Provenance:
    """Read the record attached to an instance built by the engine.

    Raises
    ------
    ConfigError
        When the instance was constructed directly or through
        ``Model.with_()``, neither of which carries a record.
    """
    record: object = getattr(model, "__provenance__", None)
    if isinstance(record, Provenance):
        return record
    msg = (
        f"{type(model).__name__} instance carries no provenance; "
        "build it with compose() or Settings.load()"
    )
    raise ConfigError(msg)


def stamp(
    record: dict[KeyPath, Origin],
    path: KeyPath,
    value: ConfigValue,
    origin: Origin,
) -> None:
    """Record a leaf write.

    Every entry at or under ``path`` is dropped, and so is every entry at
    a strict ancestor of ``path`` (a node written wholesale, or created
    empty, before a leaf below it was written); then one entry is written
    per leaf of ``value`` when it is a non-empty mapping, else one entry
    at ``path``.
    """
    prune(record, path)
    for cut in range(len(path) - 1, 0, -1):
        record.pop(path[:cut], None)
    if isinstance(value, Mapping) and value:
        for leaf_path, _ in leaves(value, path):
            record[leaf_path] = origin
    else:
        record[path] = origin


def prune(record: dict[KeyPath, Origin], path: KeyPath) -> None:
    """Drop every entry at or under ``path``."""
    depth = len(path)
    for recorded in [p for p in record if p[:depth] == path]:
        del record[recorded]


def origin_under(record: Mapping[KeyPath, Origin], path: KeyPath) -> Origin | None:
    """Find the origin of the first recorded leaf at or under ``path``.

    When none is recorded there, the nearest recorded ancestor (a leaf
    that a list or a wholesale value replaced) is returned instead;
    ``None`` when the record holds nothing on the way from the root.
    """
    depth = len(path)
    below = sorted(p for p in record if p[:depth] == path)
    if below:
        return record[below[0]]
    for cut in range(depth - 1, -1, -1):
        ancestor = path[:cut]
        if ancestor in record:
            return record[ancestor]
    return None


def complete(
    record: Mapping[KeyPath, Origin], dumped: Mapping[str, ConfigValue]
) -> Provenance:
    """Finish the record against the validated model's dump.

    Every leaf of the dump absent from the record gets ``default``; a
    leaf below a recorded path (a subtree a validator or an expression
    produced where a layer wrote one value) inherits that ancestor's
    origin; every recorded path that is not a leaf of the dump is
    dropped. The result covers exactly the leaves of the dump.
    """
    entries: dict[str, Origin] = {}
    for path, _ in leaves(dumped):
        origin = record.get(path)
        if origin is None:
            origin = _recorded_ancestor(record, path) or Origin("default")
        entries[dotted(path)] = origin
    return Provenance(entries)


def _recorded_ancestor(
    record: Mapping[KeyPath, Origin], path: KeyPath
) -> Origin | None:
    for cut in range(len(path) - 1, 0, -1):
        ancestor = path[:cut]
        if ancestor in record:
            return record[ancestor]
    return None


__all__ = [
    "Layer",
    "Origin",
    "OriginKind",
    "Provenance",
    "complete",
    "origin_under",
    "provenance_of",
    "prune",
    "stamp",
]
