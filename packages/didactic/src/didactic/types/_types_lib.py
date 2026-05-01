"""Constrained scalar types: ``EmailStr``, ``HttpUrl``, ``SecretStr``, ``Json[T]``.

Each is shorthand for ``Annotated[base_type, ...]`` with whatever
constraints / metadata didactic recognises for that shape. They give
Pydantic users a familiar surface; new code can reach for them or
write the ``Annotated`` form directly.

Examples
--------
>>> import didactic.api as dx
>>> from didactic.types import EmailStr, HttpUrl, SecretStr
>>>
>>> class User(dx.Model):
...     id: str
...     email: EmailStr
...     homepage: HttpUrl | None = None
...     api_key: SecretStr
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar, Self, cast

if TYPE_CHECKING:
    from didactic.types._types import TypeForm


@dataclass(frozen=True, slots=True)
class _StringPattern:
    """Marker that constrains a ``str`` field to a regex pattern.

    Parameters
    ----------
    pattern
        A compiled-able regex.
    label
        Human-readable label for error messages and JSON Schema
        ``format`` annotation.
    """

    pattern: str
    label: str

    def matches(self, value: str) -> bool:
        return bool(re.fullmatch(self.pattern, value))


# A loose RFC 5322 subset; enough for typical app usage.
_EMAIL_PATTERN = r"[^@\s]+@[^@\s]+\.[^@\s]+"
_URL_PATTERN = r"https?://[^\s]+"

EmailStr = Annotated[str, _StringPattern(_EMAIL_PATTERN, label="email")]
"""``Annotated[str, _StringPattern(<email regex>, "email")]`` shorthand."""

HttpUrl = Annotated[str, _StringPattern(_URL_PATTERN, label="http_url")]
"""``Annotated[str, _StringPattern(<http url regex>, "http_url")]`` shorthand."""


class SecretStr:
    """Wraps a string so its repr / serialisation hides the value.

    Parameters
    ----------
    value
        The wrapped string. Stored verbatim; never printed.

    Examples
    --------
    >>> s = SecretStr("hunter2")
    >>> repr(s)
    'SecretStr(***)'
    >>> s.get_secret_value()
    'hunter2'
    """

    __slots__ = ("_value",)
    _MASK: ClassVar[str] = "***"

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        """Return the wrapped string."""
        return self._value

    def __repr__(self) -> str:
        return f"SecretStr({self._MASK})"

    def __str__(self) -> str:
        return self._MASK

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    @classmethod
    def _coerce(cls, v: Self | str) -> Self:
        """Construct a ``SecretStr`` from a raw string or pass-through.

        Internal helper used by didactic-side adapters that need to
        accept either a ``SecretStr`` instance or a raw ``str``. The
        former pydantic-v1 ``__get_validators__`` hook used to point
        here; pydantic v2 uses ``__get_pydantic_core_schema__`` instead
        (not implemented yet).
        """
        if isinstance(v, str):
            return cls(v)
        return v


def Json(*type_args: TypeForm) -> type:  # noqa: N802
    r"""Annotation alias for "string field that holds JSON of type ``T``".

    Parameters
    ----------
    *type_args
        The expected decoded type. Use ``Json[dict[str, int]]`` style
        subscripting at the type level; the runtime alias accepts the
        same.

    Returns
    -------
    type
        A ``str`` typed annotation marked with the inner JSON type so
        downstream tooling can treat it specially.
    """
    inner: TypeForm = type_args[0] if type_args else dict

    @dataclass(frozen=True, slots=True)
    class _JsonOf:
        inner_type: TypeForm = inner

    return cast("type", Annotated[str, _JsonOf()])


__all__ = [
    "EmailStr",
    "HttpUrl",
    "Json",
    "SecretStr",
]
