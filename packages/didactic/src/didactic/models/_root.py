"""``RootModel`` and ``TypeAdapter`` for non-class typed values.

[RootModel][didactic.api.RootModel] is the equivalent of Pydantic's
``RootModel``: a Model whose payload is a single typed value rather
than a record of fields. Use it when you want didactic's validation
machinery for a list, dict, or scalar that doesn't naturally fit a
Model.

[TypeAdapter][didactic.api.TypeAdapter] is a one-off validator for an
arbitrary type, without defining a class. Useful for ad-hoc parsing
in route handlers or scripts.

Examples
--------
>>> import didactic.api as dx
>>>
>>> class IntList(dx.RootModel[tuple[int, ...]]):
...     pass
>>>
>>> IntList(root=(1, 2, 3)).root
(1, 2, 3)
>>>
>>> adapter = dx.TypeAdapter(int)
>>> adapter.validate(42)
42
"""

# ``TypeAdapter`` round-trips a generic ``T`` through the field
# translation layer; pyright doesn't bind ``T`` to ``FieldValue``.
# Tracked in panproto/didactic#1.
# pyright: reportArgumentType=false

from __future__ import annotations

from typing import TYPE_CHECKING

from didactic.models._model import Model

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue


class RootModel[T](Model):
    """A Model whose value is a single typed payload.

    Attributes
    ----------
    root
        The wrapped value. Must satisfy the type parameter ``T``.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class StringList(dx.RootModel[tuple[str, ...]]):
    ...     pass
    >>> StringList(root=("a", "b")).root
    ('a', 'b')
    """

    root: T


class TypeAdapter[T]:
    """Validate values of an arbitrary type without defining a class.

    Parameters
    ----------
    type_
        The type to validate against. Must be one didactic understands
        (str, int, float, bool, bytes, datetime, Decimal, UUID, tuple,
        frozenset, dict, Optional, Literal, Annotated).

    Examples
    --------
    >>> import didactic.api as dx
    >>> adapter = dx.TypeAdapter(int)
    >>> adapter.validate(42)
    42
    >>> adapter.validate("not an int")  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    TypeError: ...
    """

    __slots__ = ("_translation", "_type")

    def __init__(self, type_: type[T]) -> None:
        from didactic.types._types import classify  # noqa: PLC0415

        self._type = type_
        self._translation = classify(type_)

    def validate(self, value: FieldValue) -> T:
        """Validate ``value`` against the adapter's type.

        Parameters
        ----------
        value
            The value to validate.

        Returns
        -------
        T
            The validated (and possibly coerced) value.

        Raises
        ------
        TypeError
            If the value cannot be coerced to the target type.
        """
        encoded = self._translation.encode(value)
        return self._translation.decode(encoded)  # type: ignore[no-any-return]

    def dump_json(self, value: T) -> str:
        """Encode ``value`` to a JSON string."""
        import json  # noqa: PLC0415

        return json.dumps(self._translation.encode(value))


__all__ = [
    "RootModel",
    "TypeAdapter",
]
