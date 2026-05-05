"""Cached pure derivations: ``@dx.derived``.

A method decorated with [derived][didactic.api.derived] is called once
during construction; its return value is cached on the instance and
participates in [model_dump][didactic.api.Model.model_dump]. It is the
honest replacement for Pydantic's ``PrivateAttr``: a pure function of
the input fields, computed once.

Compared to [computed][didactic.api.computed]:

| feature | ``@computed`` | ``@derived`` |
| --- | --- | --- |
| evaluated... | every read | once at construction |
| stored on instance | no | yes |
| in ``model_dump`` | yes | yes |
| in storage backend | no | no (lives on ``__derived_values__``) |

Use ``@derived`` when the computation is non-trivial and the inputs
don't change after construction (which is the case for every Model,
since they're frozen).

Examples
--------
>>> import didactic.api as dx
>>>
>>> class Person(dx.Model):
...     first: str
...     last: str
...
...     @dx.derived
...     def display_name(self) -> str:
...         return f"{self.first} {self.last}"
>>>
>>> p = Person(first="Ada", last="Lovelace")
>>> p.display_name
'Ada Lovelace'
>>> p.model_dump()["display_name"]
'Ada Lovelace'

See Also
--------
didactic.computed : evaluated every read; not cached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.models._model import Model
    from didactic.types._typing import FieldValue

_DERIVED_MARKER_ATTR = "__didactic_derived__"


def derived(fn: Callable[..., FieldValue]) -> property:
    """Mark a method as a cached derivation on a [Model][didactic.api.Model].

    Parameters
    ----------
    fn
        The method to mark. Takes ``self`` and returns a value.

    Returns
    -------
    property
        A descriptor that returns the cached value on access. The
        cache lives on the instance under ``__derived_values__`` and
        is populated by the metaclass after construction.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Box(dx.Model):
    ...     w: int
    ...     h: int
    ...
    ...     @dx.derived
    ...     def area(self) -> int:
    ...         return self.w * self.h
    >>> Box(w=3, h=4).area
    12
    """
    # ``__didactic_derived__`` is a marker attribute consumed by
    # ``derived_field_names`` to discover wrapped derived methods. The
    # function-object protocol allows arbitrary attribute writes at
    # runtime; pyright models ``Callable`` as opaque so we set through
    # ``setattr`` to keep the boundary explicit.
    setattr(fn, "__didactic_derived__", True)  # noqa: B010
    name = fn.__name__

    def _getter(self: Model) -> FieldValue:
        cache = cast("dict[str, FieldValue]", getattr(self, "_derived_cache"))  # noqa: B009
        if name not in cache:
            cache[name] = fn(self)
        return cache[name]

    prop = property(_getter)
    fget = prop.fget
    if fget is not None:
        setattr(fget, "__didactic_derived__", True)  # noqa: B010
        setattr(fget, "__wrapped_name__", name)  # noqa: B010
    return prop


def derived_field_names(cls: type) -> tuple[str, ...]:
    """Return the names of all derived fields on a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    tuple
        Attribute names whose underlying property carries the
        ``__didactic_derived__`` marker. Walks MRO so inherited
        derivations are included once.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name in seen_set:
                continue
            if (
                isinstance(value, property)
                and value.fget is not None
                and hasattr(value.fget, _DERIVED_MARKER_ATTR)
            ):
                seen.append(name)
                seen_set.add(name)
    return tuple(seen)


__all__ = [
    "derived",
    "derived_field_names",
]
