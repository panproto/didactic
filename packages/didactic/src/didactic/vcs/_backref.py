# ``resolve_backrefs[A: Model]`` uses ``A`` only on the parameter
# type; pyright wants generics to bind multiple sites. The runtime
# uses ``A`` for the call-site type binding documentation. Tracked
# in panproto/didactic#1.
# pyright: reportInvalidTypeVarUse=false
"""In-memory Backref resolution.

[Backref][didactic.api.Backref] is the inverse of [Ref][didactic.api.Ref]: if
``Book`` has ``author: Ref[Author]``, an ``Author`` can ask "which
Books reference me?" without storing that information itself.

Resolution requires a *pool of candidates* to scan. didactic ships two
flavours of resolver:

[resolve_backrefs][didactic.api.resolve_backrefs]
    A direct callable: given a target Model instance and an iterable
    of candidate instances, return the subset whose ``via`` field
    equals the target's identifying attribute. Useful for one-off
    queries against a list you already have in memory.

[ModelPool][didactic.api.ModelPool]
    A small in-memory registry of Model instances, grouped by class.
    Convenient when the resolver should walk a longer-lived collection
    (for example a fixture in a test, or a cached query result).

The Repository-backed path (resolution by querying a panproto schema
via a [didactic.api.Repository][didactic.api.Repository]) lands once instance
vertices are queryable from a committed schema; the in-memory pool
covers everything that doesn't require a long-lived store.

See Also
--------
didactic.fields._refs : the marker classes that name the inverse direction.
didactic.Repository : the eventual Repository-backed resolution path.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from didactic.models._model import Model


def resolve_backrefs[A: Model, B: Model](
    target: A,
    candidates: Iterable[B],
    *,
    via: str,
    key: str = "id",
) -> list[B]:
    """Return the subset of ``candidates`` whose ``via`` field points at ``target``.

    Parameters
    ----------
    target
        The Model instance to find inbound references to.
    candidates
        An iterable of Model instances that may contain the inverse Ref.
    via
        The name of the field on each candidate that holds the Ref.
        Typically this is the field declared as ``Ref[type(target)]``.
    key
        The attribute on ``target`` whose value the Ref stores. Defaults
        to ``"id"``, which matches didactic's conventional vertex
        identifier.

    Returns
    -------
    list
        Every candidate ``c`` for which ``getattr(c, via) == getattr(target, key)``.
        The order matches the iteration order of ``candidates``.

    Raises
    ------
    AttributeError
        If ``target`` has no ``key`` attribute, or any candidate has no
        ``via`` attribute.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Author(dx.Model):
    ...     id: str
    ...     name: str
    >>> class Book(dx.Model):
    ...     id: str
    ...     title: str
    ...     author: dx.Ref[Author]
    >>> ada = Author(id="a1", name="Ada Lovelace")
    >>> books = [
    ...     Book(id="b1", title="Note A", author="a1"),
    ...     Book(id="b2", title="Note B", author="a2"),
    ...     Book(id="b3", title="Note C", author="a1"),
    ... ]
    >>> [b.id for b in dx.resolve_backrefs(ada, books, via="author")]
    ['b1', 'b3']
    """
    target_id = getattr(target, key)
    return [c for c in candidates if getattr(c, via) == target_id]


class ModelPool:
    """An in-memory pool of Model instances, grouped by class.

    Parameters
    ----------
    instances
        Optional initial collection of Model instances. Each is
        registered under its concrete class.

    Notes
    -----
    The pool is a plain dict-of-lists keyed by class identity. It does
    not deduplicate, observe mutations, or check that ids are unique;
    it is a tiny convenience for collecting test fixtures and
    short-lived application state. For durable storage, use
    [didactic.api.Repository][didactic.api.Repository].

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Author(dx.Model):
    ...     id: str
    >>> class Book(dx.Model):
    ...     id: str
    ...     author: dx.Ref[Author]
    >>>
    >>> pool = dx.ModelPool()
    >>> ada = Author(id="a1")
    >>> _ = pool.add(ada)
    >>> _ = pool.add(Book(id="b1", author="a1"))
    >>> _ = pool.add(Book(id="b2", author="a2"))
    >>>
    >>> [b.id for b in pool.backrefs(ada, Book, via="author")]
    ['b1']
    """

    __slots__ = ("_by_class",)

    def __init__(self, instances: Iterable[Model] | None = None) -> None:
        self._by_class: dict[type[Model], list[Model]] = defaultdict(list)
        if instances is not None:
            for instance in instances:
                self.add(instance)

    def add[M: Model](self, instance: M) -> M:
        """Register ``instance`` under its concrete class.

        Parameters
        ----------
        instance
            A Model instance.

        Returns
        -------
        Model
            ``instance`` itself, for fluent chaining.
        """
        self._by_class[type(instance)].append(instance)
        return instance

    def all_of[M: Model](self, cls: type[M]) -> list[M]:
        """Return every instance registered under ``cls``.

        Parameters
        ----------
        cls
            The Model class to look up.

        Returns
        -------
        list
            Instances registered under exactly ``cls`` (subclass
            instances are stored under their own concrete class, not
            under ``cls``). Order is registration order.
        """
        return list(self._by_class.get(cls, []))  # type: ignore[arg-type]

    def backrefs[A: Model, B: Model](
        self,
        target: A,
        candidate_cls: type[B],
        *,
        via: str,
        key: str = "id",
    ) -> list[B]:
        """Resolve backrefs to ``target`` from instances of ``candidate_cls``.

        Parameters
        ----------
        target
            The Model instance to find inbound references to.
        candidate_cls
            The Model class to scan for the inverse Ref.
        via
            The name of the field on ``candidate_cls`` that holds the Ref.
        key
            The attribute on ``target`` whose value the Ref stores.
            Defaults to ``"id"``.

        Returns
        -------
        list
            All registered ``candidate_cls`` instances whose ``via``
            field equals ``getattr(target, key)``.
        """
        return resolve_backrefs(
            target,
            self.all_of(candidate_cls),
            via=via,
            key=key,
        )

    def __len__(self) -> int:
        """Total number of registered instances across all classes."""
        return sum(len(v) for v in self._by_class.values())

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{cls.__name__}={len(items)}" for cls, items in self._by_class.items()
        )
        return f"ModelPool({counts})" if counts else "ModelPool()"


__all__ = [
    "ModelPool",
    "resolve_backrefs",
]
