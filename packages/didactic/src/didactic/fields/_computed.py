"""Computed fields: derived attributes that aren't stored.

A method decorated with [computed][didactic.api.computed] becomes a
derived attribute on the Model class: read-only, evaluated on access,
included in [model_dump][didactic.api.Model.model_dump]. The decorator
returns a built-in ``property``, so attribute access works through
Python's normal descriptor protocol; no metaclass tricks needed at
read time.

What the metaclass does
-----------------------
At class-creation, the metaclass scans the class dict for properties
whose underlying function carries ``__didactic_computed__`` metadata.
It collects their names into ``cls.__computed_fields__`` so that
``model_dump`` and ``model_dump_json`` can include them in their output.

Computed fields are **not** lifted into the panproto Theory unless
``materialise=True``; with that flag they become an axiom equating a
materialised constraint with the expression. (Materialisation is
deferred to a later phase that round-trips against a real
``panproto.Theory`` to discover the canonical encoding.)

See Also
--------
didactic.models._meta : the metaclass that detects computed fields.
didactic.models._model.Model.model_dump : dumps computed fields alongside stored ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.types._typing import FieldValue

_COMPUTED_MARKER_ATTR = "__didactic_computed__"


@overload
def computed(fn: Callable[..., FieldValue], /) -> property: ...


@overload
def computed(
    *, materialise: bool = False
) -> Callable[[Callable[..., FieldValue]], property]: ...


def computed(
    fn: Callable[..., FieldValue] | None = None,
    *,
    materialise: bool = False,
) -> property | Callable[[Callable[..., FieldValue]], property]:
    """Mark a method as a computed field on a [Model][didactic.api.Model].

    Parameters
    ----------
    fn
        The method to mark. Supplied positionally when the decorator is
        used without arguments (``@dx.computed``); ``None`` when the
        decorator is invoked with options (``@dx.computed(materialise=True)``).
    materialise
        Recorded on the underlying property's marker for downstream
        tooling (theory codegen, axiom emission). At the Python level
        this flag has no effect: the value is always recomputed on
        access, never stored.

    Returns
    -------
    property or Callable
        Either a ``property`` (when used directly as ``@dx.computed``) or
        a decorator that produces one (when used as
        ``@dx.computed(materialise=True)``).

    Notes
    -----
    The wrapped method should take ``self`` and return a value of any
    didactic-supported type. Computed fields participate in
    [model_dump][didactic.api.Model.model_dump] but never in storage.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Person(dx.Model):
    ...     first_name: str
    ...     last_name: str
    ...
    ...     @dx.computed
    ...     def full_name(self) -> str:
    ...         return f"{self.first_name} {self.last_name}"
    >>> p = Person(first_name="Ada", last_name="Lovelace")
    >>> p.full_name
    'Ada Lovelace'
    >>> p.model_dump()["full_name"]
    'Ada Lovelace'
    """

    def _decorate(target: Callable[..., FieldValue]) -> property:
        target.__didactic_computed__ = {"materialise": materialise}  # type: ignore[attr-defined]
        prop = property(target)
        # carry the marker on the property too so the metaclass can find
        # it without unwrapping the underlying fget
        prop.fget.__didactic_computed__ = target.__didactic_computed__  # type: ignore[union-attr]
        return prop

    if fn is None:
        return _decorate
    return _decorate(fn)


def computed_field_names(cls: type) -> tuple[str, ...]:
    """Return the names of all computed fields on a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass (or any class).

    Returns
    -------
    tuple
        The attribute names whose underlying property carries the
        ``__didactic_computed__`` marker. Walks MRO so inherited
        computed fields are included.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    # walk MRO so derived-class-shadowed names show up exactly once
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name in seen_set:
                continue
            if (
                isinstance(value, property)
                and value.fget is not None
                and hasattr(value.fget, _COMPUTED_MARKER_ATTR)
            ):
                seen.append(name)
                seen_set.add(name)
    return tuple(seen)


__all__ = [
    "computed",
    "computed_field_names",
]
