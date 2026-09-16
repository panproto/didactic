"""Type translation, typing aliases, and constrained scalar types.

The constrained types (``EmailStr``, ``HttpUrl``, ``SecretStr``,
``Json``) are re-exported so users can write::

    from didactic.types import EmailStr, HttpUrl

``unwrap_annotated`` is re-exported for tooling that reads a field's
annotation back to its base type (the composition engine in
``didactic-settings`` recovers nested model classes with it).
"""

from didactic.types._types import unwrap_annotated
from didactic.types._types_lib import EmailStr, HttpUrl, Json, SecretStr

__all__ = [
    "EmailStr",
    "HttpUrl",
    "Json",
    "SecretStr",
    "unwrap_annotated",
]
