# Models

A `dx.Model` subclass is a frozen, type-checked record. The metaclass
walks the declared annotations once at class-creation time and builds
a [FieldSpec][didactic.api.FieldSpec] per field. Subsequent operations
(construction, attribute access, serialisation) work off those specs.

## Declaration

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str
    nickname: str = ""
```

The class docstring becomes the description in JSON Schema and other
schema-format exports.

## Construction

`User` accepts keyword arguments. Required fields must be supplied;
optional fields take their declared default.

A construction call validates each value against its annotation, runs
any [`@validates`](validators.md) methods, and evaluates any
[axioms](axioms.md). Failures raise
[didactic.api.ValidationError][didactic.api.ValidationError] with one
[ValidationErrorEntry][didactic.api.ValidationErrorEntry] per failure.

## Immutability

Every Model instance is frozen. Direct attribute assignment raises:

```python
u.email = "elsewhere"
# AttributeError
```

To produce a modified copy, use [Model.with_][didactic.api.Model.with_]:

```python
u2 = u.with_(email="elsewhere@example.org")
```

`with_` validates the new fields, so the result is always a
well-formed Model.

## Equality and hashing

Two Models compare equal when their classes are identical and every
field has an equal value. Models hash on the same key.

## Inheritance

Subclassing extends the field set. The parent's fields appear before
the child's in the canonical iteration order:

```python
class TimestampedUser(User):
    created_at: datetime.datetime
```

Theory derivation handles single inheritance transparently; multi
inheritance triggers a panproto colimit. See
[Inheritance](inheritance.md).

## Generic Models

PEP 695 generics work directly:

```python
class Box[T](dx.Model):
    item: T


class IntBox(Box[int]):
    pass


IntBox(item=42)
```

The base `Box[T]` is abstract: constructing it directly raises a
`TypeError` with a message that says the class is generic and must
be parameterised first.

## Inspecting a class

Every Model exposes:

- `__field_specs__`: mapping field name to
  [FieldSpec][didactic.api.FieldSpec].
- `__class_axioms__`: the tuple of class-level
  [Axiom][didactic.api.Axiom] records.
- `__computed_fields__`: the names of `@computed` properties.
- `__theory__`: the lazily-built `panproto.Theory` (computed on
  first access).
