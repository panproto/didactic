# First model

Every didactic application starts the same way: declare a subclass of
[didactic.api.Model][didactic.api.Model] and write the fields as ordinary
type-annotated class attributes.

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str
    nickname: str = ""
```

That is the whole class. There is no metaclass call, no field
constructor, and no schema declaration alongside.

## Construction

`User` is a callable that accepts keyword arguments matching the
declared fields:

```python
u = User(id="u1", email="ada@example.org")
```

Required fields (`id`, `email`) must be supplied. Optional fields
(`nickname`) take their declared default when omitted.

A missing required field, an unknown field, or a value that does not
match its annotation raises a [didactic.api.ValidationError][didactic.api.ValidationError]:

```python
User()                                         # missing id and email
User(id="u1", email="ada", surprise="hi")      # unknown field
User(id="u1", email=42)                        # email is not a str
```

Each of these surfaces with one or more
[ValidationErrorEntry][didactic.api.ValidationErrorEntry] records, each
of which carries a `loc`, a `type` discriminator, and a `msg`.

## Attribute access

Field values are read by attribute access:

```python
u.id            # 'u1'
u.email         # 'ada@example.org'
u.nickname      # ''
```

The class has no `__init__` you have to write, no per-field
descriptors to maintain, and no parallel storage for the values you
just supplied.

## Immutability

Models are frozen. Reassigning a field raises:

```python
u.email = "elsewhere"
# AttributeError: User is immutable; use `.with_(email=...)` to produce a new instance
```

To produce a modified copy, use [Model.with_][didactic.api.Model.with_]:

```python
u2 = u.with_(email="elsewhere@example.org")
```

`u` and `u2` are separate instances. didactic depends on this; the
lens layer, the structural fingerprint, and the schema repository all
assume that values are content-addressed.

## What you have

After this chapter you have a Model that:

- accepts and rejects construction arguments by type and presence,
- exposes its fields by attribute access,
- is immutable, with a documented update path.

[Next: fields and types](02-fields.md).
