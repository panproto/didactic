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
| `pathlib.Path` | string | `Path` |
| `enum.Enum` | member name | `Enum` |

The encoded form is what panproto stores. JSON output uses the same
encoded form, with one extra step that turns hex `bytes` into a
JSON string and `frozenset` into a sorted list.

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
