"""Type translation, typing aliases, and constrained scalar types.

The constrained types (``EmailStr``, ``HttpUrl``, ``SecretStr``,
``Json``) are re-exported so users can write::

    from didactic.types import EmailStr, HttpUrl
"""

from didactic.types._types_lib import EmailStr, HttpUrl, Json, SecretStr

__all__ = [
    "EmailStr",
    "HttpUrl",
    "Json",
    "SecretStr",
]
