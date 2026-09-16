"""Origin records and the layer record that carries them.

An :class:`Origin` says which rung of the precedence ladder wrote a
value; a :class:`Layer` is one document tagged with the origin every leaf
it sets will carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from didactic.settings._values import ConfigValue

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


__all__ = ["Layer", "Origin", "OriginKind"]
