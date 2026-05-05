# Types

didactic understands three kinds of type:

1. Scalars: built-in primitives plus a small set of stdlib types.
2. Containers: `tuple`, `frozenset`, and `dict[str, V]` (immutable
   only).
3. Constrained scalars: `Annotated[T, ...]` annotations whose
   metadata didactic interprets.

Mutable containers (`list`, `set`, plain `dict`) are rejected. Use
`tuple[T, ...]`, `frozenset[T]`, or `dict[str, V]`.

## Built-in scalars

| annotation | encoded as | decoded back to |
| --- | --- | --- |
| `str` | string | `str` |
| `int` | string | `int` |
| `float` | string | `float` |
| `bool` | string `"true"` / `"false"` | `bool` |
| `bytes` | hex string | `bytes` |
| `datetime.datetime` | ISO 8601 | `datetime` |
| `datetime.date` | ISO 8601 | `date` |
| `datetime.time` | ISO 8601 | `time` |
| `datetime.timedelta` | seconds | `timedelta` |
| `decimal.Decimal` | numeric string | `Decimal` |
| `uuid.UUID` | canonical | `UUID` |
| `pathlib.Path` (and any `PurePath` subclass) | string | the same `PurePath` subclass |
| `enum.StrEnum` | string (the member value) | `StrEnum` member |
| `enum.IntEnum` | integer (the member value) | `IntEnum` member |
| `enum.Enum` (string- or int-valued) | the member value | `Enum` member |

The encoded form is what panproto stores. JSON output uses the same
encoded form, with one extra step that turns hex `bytes` into a
JSON string and `frozenset` into a sorted list.

## Paths and enums

`pathlib.Path` and any `PurePath` subclass round-trip as strings:

```python
from pathlib import Path

class Cfg(dx.Model):
    data_dir: Path
```

`enum.StrEnum` round-trips as a string (the member value);
`enum.IntEnum` round-trips as an integer. Plain `enum.Enum` works
when every member's value is a string or every member's value is an
integer; mixed-value enums raise `TypeNotSupportedError`.

```python
from enum import StrEnum

class Color(StrEnum):
    RED = "red"
    BLUE = "blue"

class Item(dx.Model):
    color: Color
```

Construction accepts either an enum member or its raw value, so
`Item.model_validate({"color": "red"})` works the same as
`Item(color=Color.RED)`.

## Optional types

`T | None` is supported directly. The encoded form is the value when
present, the JSON `null` when absent.

```python
class User(dx.Model):
    id: str
    nickname: str | None = None
```

## Containers

| annotation | notes |
| --- | --- |
| `tuple[T, ...]` | variable-length tuple of `T` |
| `tuple[A, B, C]` | fixed-shape tuple |
| `frozenset[T]` | order-insensitive set |
| `dict[str, V]` | string-keyed map; string keys only |
| `Literal["a", "b", ...]` | enumerated literal |

A field whose annotation contains a list, set, or plain dict raises
`TypeNotSupportedError` at class-creation time.

## Constrained scalars from `didactic.types`

`didactic.types` re-exports a small library of constrained scalar
annotations:

| name | annotation | constraint |
| --- | --- | --- |
| `EmailStr` | `Annotated[str, ...]` | regex matching an email shape |
| `HttpUrl` | `Annotated[str, ...]` | regex matching `https?://...` |
| `SecretStr` | wrapper class | masked `repr` and `str` |
| `Json[T]` | `Annotated[str, ...]` | string field that holds JSON |

Use them as drop-in annotations:

```python
from didactic.types import EmailStr, HttpUrl, SecretStr


class User(dx.Model):
    id: str
    email: EmailStr
    homepage: HttpUrl | None = None
    api_key: SecretStr
```

`SecretStr` does not derive from `str`; call `.get_secret_value()` to
retrieve the wrapped value.

## Adding a custom scalar

If you want a type didactic does not natively understand, attach a
[converter][didactic.api.field] that produces an instance of a supported
type, or write a custom emitter (see [Code generation](codegen.md)).
A first-class `dx.register_encoder(type, encoder)` API for adding
new scalars is on the roadmap.

## TypeAdapter for one-off validation

`dx.TypeAdapter(T)` validates values of an arbitrary type without
declaring a class:

```python
adapter = dx.TypeAdapter(int)
adapter.validate(42)            # 42
adapter.dump_json(42)           # '"42"'
```

## RootModel for non-record payloads

`dx.RootModel[T]` wraps a single typed payload as a Model:

```python
class IntList(dx.RootModel[tuple[int, ...]]):
    pass


IntList(root=(1, 2, 3)).root
# (1, 2, 3)
```

Use `RootModel` when your value is naturally a list, dict, or scalar
rather than a record.
