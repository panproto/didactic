"""Pluggable storage backend for Model instances.

The design contract is that a ``Model`` instance
carries exactly one ``panproto.Schema`` and decodes from it on every
attribute access. v0.0.1 ships a dict-backed stand-in so the Model layer
can be authored and exercised before the panproto runtime is wired in.
The Schema-backed implementation drops in behind the same interface.

Notes
-----
The interface is deliberately minimal: get an encoded value by field name,
produce a new storage with one or more fields replaced, iterate over field
names. The encode/decode layer lives in
[didactic.fields._fields][] / [didactic.api.types._types][]; this module only
stores already-encoded strings.

See Also
--------
didactic.models._model : the consumer of this interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@runtime_checkable
class _NotMine(Protocol):
    """Sentinel Protocol for "any value other than this class".

    Used in ``__eq__`` overrides where the convention requires accepting
    arbitrary other values to satisfy LSP, but we still want to avoid
    bare ``object`` as a type hint.
    """


@runtime_checkable
class ModelStorage(Protocol):
    """The contract every Model storage backend must satisfy."""

    def get(self, name: str) -> str:
        """Return the encoded value for one field.

        Parameters
        ----------
        name
            The field's Python attribute name.

        Returns
        -------
        str
            The panproto-shaped encoded value.

        Raises
        ------
        KeyError
            If the field is not stored.
        """
        ...

    def replaced(self, changes: Mapping[str, str]) -> ModelStorage:
        """Return a new storage with the given encoded fields replaced.

        Parameters
        ----------
        changes
            Mapping of field name to encoded value. Unaffected fields
            carry over from ``self``.

        Returns
        -------
        ModelStorage
            A new storage; ``self`` is unchanged.
        """
        ...

    def names(self) -> Iterable[str]:
        """Iterate over the field names stored here."""
        ...

    def to_dict(self) -> dict[str, str]:
        """Materialise the storage as ``{field_name: encoded_value}``."""
        ...


class DictStorage:
    """Trivial dict-backed [ModelStorage][didactic.models._storage.ModelStorage].

    Used in v0.0.1 before the panproto runtime is wired in. Holds an
    immutable mapping of field name to encoded value.

    Parameters
    ----------
    items
        The encoded values, keyed by field name.

    Notes
    -----
    The underlying dict is copied on construction to enforce immutability.
    Successive ``replaced`` calls produce fresh DictStorages; structural
    sharing (the panproto-side optimisation) is not implemented here.
    """

    __slots__ = ("_items",)

    def __init__(self, items: Mapping[str, str]) -> None:
        # store a real dict so `get` never accidentally mutates
        self._items: dict[str, str] = dict(items)

    def get(self, name: str) -> str:
        """Return the encoded value, raising ``KeyError`` if missing."""
        return self._items[name]

    def replaced(self, changes: Mapping[str, str]) -> DictStorage:
        """Return a new DictStorage with ``changes`` overlaid."""
        if not changes:
            return self
        merged = dict(self._items)
        merged.update(changes)
        return DictStorage(merged)

    def names(self) -> Iterable[str]:
        """Iterate over stored field names."""
        return iter(self._items)

    def to_dict(self) -> dict[str, str]:
        """Materialise as a fresh dict."""
        return dict(self._items)

    def __eq__(self, other: DictStorage | _NotMine) -> bool:  # type: ignore[override]
        """Two DictStorages are equal iff their item maps are equal."""
        if not isinstance(other, DictStorage):
            return NotImplemented
        return self._items == other._items

    def __hash__(self) -> int:
        """Hash by the canonical item set."""
        return hash(tuple(sorted(self._items.items())))

    def __repr__(self) -> str:
        """Compact dict-style repr."""
        return f"DictStorage({self._items!r})"


__all__ = [
    "DictStorage",
    "ModelStorage",
]
