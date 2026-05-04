"""Lenses, isomorphisms, and one-way mappings between Models.

This module ships the pure-Python authoring surface for lenses. The
panproto-side hookup (each [Lens][didactic.api.Lens] instance compiling to a
``panproto.Lens`` so we get formal complement-bearing get/put with the
GetPut/PutGet laws) lands once we round-trip against a runnable
panproto. Until then, lenses behave as regular Python objects with
forward/backward methods and ``>>`` composition.

Three flavours
--------------

[Mapping][didactic.api.Mapping]
    One-way function ``A -> B``. Cannot be inverted; suitable for
    transforms that lose information without recovery.
[Iso][didactic.api.Iso]
    Two-way bijection ``A -> B`` and ``B -> A``. The complement is
    the unit type; no information dropped.
[Lens][didactic.api.Lens]
    The general case. ``forward(a) -> (b, complement)`` and
    ``backward(b, complement) -> a``. Round-trip laws:
    ``backward(*forward(a)) == a`` (GetPut) and
    ``forward(backward(b, c)) == (b, c)`` (PutGet).

Composition is associative with identity. ``L1 >> L2`` produces a new
lens whose forward applies ``L1.forward`` then ``L2.forward``.

Examples
--------
>>> import didactic.api as dx
>>>
>>> class User(dx.Model):
...     id: str
...     email: str
>>>
>>> class LowercaseEmail(dx.Iso[User, User]):
...     def forward(self, u: User) -> User:
...         return u.with_(email=u.email.lower())
...
...     def backward(self, u_after: User) -> User:
...         return u_after  # no information dropped
>>>
>>> u = User(id="u1", email="ALICE@example.com")
>>> LowercaseEmail()(u).email
'alice@example.com'

See Also
--------
didactic.theory._theory : the bridge that will compile lenses to panproto.Lens.
"""

# ``lens`` doubles as a callable and a namespace (``dx.lens.identity``);
# the namespace attributes are stamped on the function object.
from __future__ import annotations

import functools
from typing import (
    TYPE_CHECKING,
    ClassVar,
    cast,
    get_args,
    get_origin,
)

from didactic.types._typing import Opaque

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Mapping (one-way)
# ---------------------------------------------------------------------------


class Mapping[A, B]:
    """One-way transformation from ``A`` to ``B``.

    Subclass and override [forward][didactic.api.Mapping.forward]. Cannot be
    composed in reverse and has no [inverse][didactic.api.Iso.inverse].

    Notes
    -----
    Mappings are pure Python in v0.0.2; the panproto-side ``Lens``
    representation lands later.

    See Also
    --------
    didactic.Iso : a Mapping with a verified inverse.
    didactic.Lens : a Mapping with a complement.
    """

    #: Source and target classes inferred from the type parameters at
    #: subclass time. ``None`` until a subclass is created with a
    #: ``Mapping[A, B]`` parameter list.
    __source__: ClassVar[type | None] = None
    __target__: ClassVar[type | None] = None

    def __init_subclass__(cls, **kwargs: Opaque) -> None:
        """Record source/target from the ``Mapping[A, B]`` parameterisation."""
        super().__init_subclass__(**kwargs)
        # walk the original bases for `Mapping[A, B]` / `Iso[A, B]` / `Lens[A, B]`
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is None:
                continue
            if origin is Mapping or origin is Iso or origin is Lens:
                args = get_args(base)
                if args:
                    cls.__source__ = args[0] if isinstance(args[0], type) else None
                    cls.__target__ = args[-1] if isinstance(args[-1], type) else None
                    break

    def forward(self, a: A, /) -> B:
        """Map ``a`` forward to its target.

        Subclasses must override. The default raises
        ``NotImplementedError`` so misuse is loud.
        """
        msg = (
            f"{type(self).__name__} must override `forward(a) -> b`. "
            "(Are you sure you didn't mean to subclass Iso or Lens?)"
        )
        raise NotImplementedError(msg)

    def __call__(self, a: A) -> B:
        """Sugar for ``self.forward(a)``."""
        return self.forward(a)

    def __rshift__[C](self, other: Mapping[B, C]) -> Mapping[A, C]:
        """Compose left-to-right: ``(self >> other)(a) == other(self(a))``."""
        # Defensive: Python's NotImplemented protocol expects ``__rshift__``
        # to fall through cleanly when given an unrelated object. We can't
        # express ``Mapping[B, C] | object`` in a useful way, so we route
        # through ``cast(object, ...)`` to disable narrowing for the runtime
        # check that guards the NotImplemented return.
        if not isinstance(cast("object", other), Mapping):
            return NotImplemented
        return _ComposedMapping(self, other)

    def __repr__(self) -> str:
        """Render with class name and source/target."""
        cls = type(self)
        src = cls.__source__.__name__ if cls.__source__ else "?"
        tgt = cls.__target__.__name__ if cls.__target__ else "?"
        return f"{cls.__name__}[{src}, {tgt}]"


# ---------------------------------------------------------------------------
# Iso (two-way, no complement)
# ---------------------------------------------------------------------------


class Iso[A, B](Mapping[A, B]):
    """Two-way bijection between ``A`` and ``B`` with no information loss.

    Subclass and override [forward][didactic.api.Iso.forward] and
    [backward][didactic.api.Iso.backward]. Round-trip laws are:

    - ``backward(forward(a)) == a``
    - ``forward(backward(b)) == b``

    didactic verifies these in tests via
    [didactic.api.testing.verify_iso][]; runtime verification on every
    forward call is opt-in.

    See Also
    --------
    didactic.Lens : the general lossy lens with a complement.
    """

    def backward(self, b: B, /) -> A:
        """Map ``b`` back to its source. Subclasses override."""
        msg = f"{type(self).__name__} must override `backward(b) -> a`."
        raise NotImplementedError(msg)

    def inverse(self) -> Iso[B, A]:
        """Return an Iso that swaps forward and backward."""
        return _InverseIso(self)


# ---------------------------------------------------------------------------
# Lens (forward returns complement, backward takes complement)
# ---------------------------------------------------------------------------


class Lens[A, B, C = Opaque]:
    """General bidirectional transform with a complement.

    Subclass and override [forward][didactic.api.Lens.forward] returning
    ``(b, complement)``, and [backward][didactic.api.Lens.backward] taking
    ``(b, complement)`` and returning ``a``. Round-trip laws (panproto's
    ``check_get_put`` and ``check_put_get``):

    - GetPut: ``backward(*forward(a)) == a``
    - PutGet: ``forward(backward(b, c)) == (b, c)``

    Notes
    -----
    The pure-Python implementation does not enforce the laws; they are
    tested with hypothesis or verified through panproto once the runtime
    hookup lands.

    See Also
    --------
    didactic.Iso : the lossless special case (complement is unit).
    didactic.Mapping : one-way variant.
    """

    __source__: ClassVar[type | None] = None
    __target__: ClassVar[type | None] = None

    def __init_subclass__(cls, **kwargs: Opaque) -> None:
        """Record source/target from the ``Lens[A, B]`` parameterisation."""
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is Lens:
                args = get_args(base)
                if args:
                    cls.__source__ = args[0] if isinstance(args[0], type) else None
                    cls.__target__ = args[1] if isinstance(args[1], type) else None
                    break

    def forward(self, a: A, /) -> tuple[B, C]:
        """Project ``a`` to ``(b, complement)``. Subclasses override."""
        msg = f"{type(self).__name__} must override `forward(a) -> (b, complement)`."
        raise NotImplementedError(msg)

    def backward(self, b: B, complement: C, /) -> A:
        """Reconstruct ``a`` from ``(b, complement)``. Subclasses override."""
        msg = f"{type(self).__name__} must override `backward(b, complement) -> a`."
        raise NotImplementedError(msg)

    def __call__(self, a: A, /) -> tuple[B, C]:
        """Sugar for ``self.forward(a)``."""
        return self.forward(a)

    def __rshift__[D, E](self, other: Lens[B, D, E]) -> Lens[A, D, tuple[C, E]]:
        """Compose two lenses left-to-right.

        The composite's complement is a tuple of the components' complements.
        """
        # See ``Mapping.__rshift__`` for why this isinstance check exists
        # and why we route through ``cast(object, ...)``.
        if not isinstance(cast("object", other), Lens):
            return NotImplemented
        return _ComposedLens(self, other)

    def __repr__(self) -> str:
        """Render with class name and source/target."""
        cls = type(self)
        src = cls.__source__.__name__ if cls.__source__ else "?"
        tgt = cls.__target__.__name__ if cls.__target__ else "?"
        return f"{cls.__name__}[{src}, {tgt}]"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class _Identity[A](Iso[A, A]):
    """Identity Iso: ``forward(x) == x`` and ``backward(x) == x``."""

    def __init__(self, source: type[A] | None = None) -> None:
        # capture the source class at construction so __repr__ reads cleanly
        self._source_at_runtime = source

    def forward(self, a: A) -> A:
        return a

    def backward(self, b: A) -> A:
        return b


def identity[A](source: type[A]) -> Iso[A, A]:
    """Return the identity isomorphism on ``source``.

    Parameters
    ----------
    source
        The Model class.

    Returns
    -------
    Iso
        An ``Iso[source, source]`` whose forward and backward are both
        the identity function.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class User(dx.Model):
    ...     id: str
    >>> id_user = dx.lens.identity(User)
    >>> u = User(id="u1")
    >>> id_user(u) is u
    True
    """
    iso: Iso[A, A] = _Identity(source)
    return iso


# ---------------------------------------------------------------------------
# Composition helpers (private)
# ---------------------------------------------------------------------------


class _ComposedMapping[A, B, C](Mapping[A, C]):
    """Composition of two Mappings."""

    def __init__(self, first: Mapping[A, B], second: Mapping[B, C]) -> None:
        self._first = first
        self._second = second

    def forward(self, a: A) -> C:
        return self._second.forward(self._first.forward(a))

    def __repr__(self) -> str:
        return f"({self._first!r} >> {self._second!r})"


class _InverseIso[A, B](Iso[B, A]):
    """An Iso that flips an existing Iso."""

    def __init__(self, inner: Iso[A, B]) -> None:
        self._inner = inner

    def forward(self, b: B) -> A:
        return self._inner.backward(b)

    def backward(self, a: A) -> B:
        return self._inner.forward(a)

    def inverse(self) -> Iso[A, B]:
        return self._inner

    def __repr__(self) -> str:
        return f"~{self._inner!r}"


class _ComposedLens[A, B, C, C1, C2](Lens[A, C, tuple[C1, C2]]):
    """Composition of two general Lenses."""

    def __init__(self, first: Lens[A, B, C1], second: Lens[B, C, C2]) -> None:
        self._first = first
        self._second = second

    def forward(self, a: A, /) -> tuple[C, tuple[C1, C2]]:
        b, c1 = self._first.forward(a)
        c, c2 = self._second.forward(b)
        return c, (c1, c2)

    def backward(self, c: C, complement: tuple[C1, C2], /) -> A:
        c1, c2 = complement
        b = self._second.backward(c, c2)
        return self._first.backward(b, c1)

    def __repr__(self) -> str:
        return f"({self._first!r} >> {self._second!r})"


# ---------------------------------------------------------------------------
# @lens decorator (function -> Mapping)
# ---------------------------------------------------------------------------


class _LensNamespace:
    """Callable namespace for ``dx.lens``.

    Doubles as a decorator (``@dx.lens(A, B)``) and as a module-style
    namespace exposing convenience attributes (``dx.lens.identity``,
    ``dx.lens.Lens``, ``dx.lens.Iso``, ``dx.lens.Mapping``).
    """

    identity: Callable[..., Iso[Opaque, Opaque]]
    Lens: type[Lens[Opaque, Opaque, Opaque]]
    Iso: type[Iso[Opaque, Opaque]]
    Mapping: type[Mapping[Opaque, Opaque]]

    def __init__(self) -> None:
        # ``identity`` is parameterised on ``A``; the namespace exposes the
        # erased ``Opaque, Opaque`` shape since callers re-bind on use.
        self.identity = cast("Callable[..., Iso[Opaque, Opaque]]", identity)
        self.Lens = Lens
        self.Iso = Iso
        self.Mapping = Mapping

    def __call__[A, B](
        self, source: type[A], target: type[B]
    ) -> Callable[[Callable[[A], B]], Mapping[A, B]]:
        """Wrap a plain function as a [Mapping][didactic.api.Mapping].

        Parameters
        ----------
        source
            The source Model class.
        target
            The target Model class.

        Returns
        -------
        Callable
            A decorator that turns ``fn(a) -> b`` into a Mapping subclass
            instance suitable for ``>>`` composition.

        Examples
        --------
        >>> import didactic.api as dx
        >>>
        >>> class User(dx.Model):
        ...     id: str
        ...     email: str
        >>>
        >>> @dx.lens(User, User)
        ... def lowercase_email(u: User) -> User:
        ...     return u.with_(email=u.email.lower())
        >>>
        >>> u = User(id="u1", email="ALICE@example.com")
        >>> lowercase_email(u).email
        'alice@example.com'
        """

        def decorate(fn: Callable[[A], B]) -> Mapping[A, B]:
            @functools.wraps(fn, updated=())
            class _DecoratedMapping(Mapping[A, B]):  # type: ignore[no-redef]
                __source__ = source
                __target__ = target

                def forward(self, a: A, /) -> B:
                    return fn(a)

            return _DecoratedMapping()

        return decorate


lens = _LensNamespace()

__all__ = [
    "Iso",
    "Lens",
    "Mapping",
    "identity",
    "lens",
]
