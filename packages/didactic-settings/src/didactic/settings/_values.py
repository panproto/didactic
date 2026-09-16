"""The value shape the engine operates on, and path helpers over it.

A config document is a tree of JSON-shaped values: the list-based shape
that ``json.loads``, ``tomllib.load`` and ``yaml.safe_load`` all produce
and that didactic validation accepts for ``tuple[T, ...]`` fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

type ConfigValue = (
    str | int | float | bool | None | Sequence[ConfigValue] | Mapping[str, ConfigValue]
)
"""A JSON-shaped config value: scalars, ``None``, lists and string-keyed dicts.

The container arms are spelled with the covariant ``Sequence`` and
``Mapping`` so a narrowly inferred literal (``{"a": {"b": "x"}}``, typed
``dict[str, dict[str, str]]``) is accepted wherever a ``ConfigValue`` is
expected. At runtime the engine builds and checks for ``list`` and
``dict``.
"""

type KeyPath = tuple[str, ...]
"""A path of dict keys from the document root to a node."""


def dotted(path: KeyPath) -> str:
    """Render a key path as a dotted string.

    A segment spelled ``[i]`` (a list element checked by the merge) is
    joined without a dot, so ``("items", "[0]", "bogus")`` renders as
    ``items[0].bogus``.
    """
    out = ""
    for segment in path:
        if not out or segment.startswith("["):
            out += segment
        else:
            out += "." + segment
    return out


def leaves(
    document: Mapping[str, ConfigValue], prefix: KeyPath = ()
) -> Iterator[tuple[KeyPath, ConfigValue]]:
    """Yield ``(path, value)`` for every leaf of a document.

    A non-empty dict descends; an empty dict is a leaf; a list is a leaf
    (lists are set wholesale, elements are not addressed); every scalar
    and ``None`` is a leaf. This is the one leaf definition shared by the
    merge, provenance completion and the coverage law over
    ``model_dump_json()``.
    """
    for key, value in document.items():
        path = (*prefix, key)
        if isinstance(value, Mapping) and value:
            yield from leaves(value, path)
        else:
            yield path, value


def nest_override(dotted_key: str, value: ConfigValue) -> dict[str, ConfigValue]:
    """Wrap a value under a dotted key, one nested dict per segment.

    ``nest_override("model.type_encoder.num_heads", 8)`` gives
    ``{"model": {"type_encoder": {"num_heads": 8}}}``. The key's syntax is
    validated by :func:`~didactic.settings.parse_override`; this function
    only builds the tree.
    """
    segments = dotted_key.split(".")
    tree: dict[str, ConfigValue] = {segments[-1]: value}
    for segment in reversed(segments[:-1]):
        tree = {segment: tree}
    return tree


__all__ = ["ConfigValue", "KeyPath", "dotted", "leaves", "nest_override"]
