# Fields and types

A field with no metadata beyond its annotation is just an annotated
class attribute. To attach a description, an alias, examples, or
validation metadata, use [didactic.api.field][didactic.api.field] in place
of the default value:

```python
import didactic.api as dx


class User(dx.Model):
    id: str = dx.field(description="primary key")
    email: str = dx.field(description="primary contact")
    nickname: str = ""
    legacy_id: str | None = dx.field(default=None, deprecated=True)
```

`dx.field(...)` accepts the same metadata Pydantic users will
recognise:

| keyword | purpose |
| --- | --- |
| `default` | the default value when the field is omitted |
| `default_factory` | a zero-argument callable that produces the default |
| `alias` | external serialisation name |
| `description` | one-line description, surfaced in JSON Schema |
| `examples` | a tuple of example values |
| `deprecated` | flag the field as deprecated; surfaced in JSON Schema |
| `nominal` | mark the field as part of vertex identity |
| `extras` | arbitrary metadata; round-trips through Pydantic |

## Built-in types

The metaclass accepts the following annotations directly:

| annotation | how it is stored |
| --- | --- |
| `str`, `int`, `float`, `bool`, `bytes` | as-is |
| `datetime.datetime`, `date`, `time`, `timedelta` | ISO 8601 string |
| `decimal.Decimal` | numeric string |
| `uuid.UUID` | canonical string |
| `pathlib.Path` | string |
| `T | None` | the value or `None` |
| `tuple[T, ...]` | tuple |
| `frozenset[T]` | frozenset (sorted on JSON dump) |
| `dict[str, V]` | dict |
| `Literal["a", "b", ...]` | literal value |
| `Annotated[T, ...]` | as `T`, with the metadata stored on the FieldSpec |

Mutable containers (`list`, `set`, plain `dict`) are rejected. Use
their immutable counterparts.

## Constrained scalar types

`didactic.types` provides the conventional set of constrained
scalars:

```python
from didactic.types import EmailStr, HttpUrl, SecretStr


class User(dx.Model):
    id: str
    email: EmailStr
    homepage: HttpUrl | None = None
    api_key: SecretStr
```

`EmailStr` and `HttpUrl` are `Annotated[str, ...]` aliases that carry
a regex pattern. `SecretStr` is a wrapper class whose `repr` and
`str` mask the value; call `.get_secret_value()` to retrieve it.

## Annotated constraints

Constraint primitives from [annotated-types](https://github.com/annotated-types/annotated-types)
flow through verbatim. They become axioms on the Model and propagate
to the JSON Schema:

```python
from typing import Annotated
from annotated_types import Ge, Le


class Pixel(dx.Model):
    x: Annotated[int, Ge(0), Le(1023)]
    y: Annotated[int, Ge(0), Le(1023)]


Pixel(x=42, y=42)         # ok
Pixel(x=-1, y=42)         # raises ValidationError
```

[Next: validation](03-validation.md).
