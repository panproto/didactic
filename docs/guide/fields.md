# Fields

A field is a type-annotated class attribute on a `dx.Model`. The
default value, when present, is either a plain value, a
[didactic.api.field][didactic.api.field] descriptor, or one of the marker
classes from `didactic.fields._refs` (`Ref`, `Embed`, `Backref`).

## Plain defaults

```python
class User(dx.Model):
    id: str
    nickname: str = ""             # plain default
    role: str = "member"
```

A plain default is used verbatim when the field is omitted at
construction.

## `dx.field(...)` for metadata

When you want to attach more than a default value, use
[didactic.api.field][didactic.api.field]:

```python
class User(dx.Model):
    id: str = dx.field(description="primary key")
    email: str = dx.field(
        description="primary contact",
        examples=("ada@example.org",),
    )
    legacy_id: str | None = dx.field(default=None, deprecated=True)
```

The accepted keywords are:

| keyword | type | purpose |
| --- | --- | --- |
| `default` | any | default value |
| `default_factory` | callable | zero-argument default-producing callable |
| `alias` | `str` | name used in `model_dump(by_alias=True)` |
| `description` | `str` | one-line description |
| `examples` | tuple | example values |
| `deprecated` | `bool` | flag the field as deprecated |
| `nominal` | `bool` | mark the field as part of vertex identity |
| `converter` | callable | PEP 712 converter applied before type checks |
| `extras` | dict | arbitrary metadata; round-trips through Pydantic |

## Defaults and factories

Use `default` for values, `default_factory` for callables (most
commonly a zero-argument function returning a fresh container):

```python
class Order(dx.Model):
    id: str
    items: tuple[str, ...] = dx.field(default_factory=tuple)
```

Supplying both is an error; supplying neither makes the field
required.

## Aliases

`alias` is the name used in serialisation when `by_alias=True`:

```python
class User(dx.Model):
    user_id: str = dx.field(alias="userId")
    email: str

User(user_id="u1", email="a@b").model_dump(by_alias=True)
# {'userId': 'u1', 'email': 'a@b'}
```

Aliases also flow to JSON Schema and the Pydantic adapter.

## Annotated metadata

Anything passed inside `Annotated[T, ...]` is read by the metaclass.
Supported markers:

- `annotated_types.Ge`, `Gt`, `Le`, `Lt`, `MinLen`, `MaxLen`,
  `MultipleOf`, `Predicate`. These produce axioms automatically and
  flow to JSON Schema as `minimum`, `maximum`, etc.
- `typing.Doc` (PEP 727). Populates the field's `description` if
  `dx.field(description=...)` is not also set.
- The marker classes from `didactic._refs` (`RefMarker`,
  `EmbedMarker`, `BackrefMarker`). Set automatically when you write
  `Ref[T]`, `Embed[T]`, or `Backref[T, "field"]`.
- Custom metadata that didactic does not recognise is preserved
  verbatim in `FieldSpec.extras["annotated_metadata"]` so downstream
  tooling can read it.

## Field inspection

`__field_specs__` exposes every field's resolved record:

```python
spec = User.__field_specs__["email"]
spec.annotation       # <class 'str'>
spec.is_required      # True
spec.description      # 'primary contact'
spec.translation.sort # 'User_email'
```

See the [FieldSpec reference](../reference/field.md) for the full
attribute list.
