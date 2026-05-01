# Validators

[didactic.api.validates][didactic.api.validates] decorates a method as a
per-field check that runs at construction time:

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str

    @dx.validates("email")
    def _email_must_have_at(self, value: str) -> bool:
        return "@" in value
```

The validator runs after the field's type translation. Its argument
is the decoded value; its return value must be `bool`. `False`
raises a `ValidationError` with a `validates_failed` entry.

## Multiple validators per field

Multiple `@validates` methods on the same field run in declaration
order. The first failure short-circuits the rest for that field.

## Cross-field invariants

`@validates` runs against one field at a time. For a check that
spans multiple fields, declare an [axiom](axioms.md) instead:

```python
class Range(dx.Model):
    low: int
    high: int

    __axioms__ = [dx.axiom("low <= high")]
```

## Validation error shape

```python
try:
    User(id="u1", email="not-an-email")
except dx.ValidationError as exc:
    exc.entries        # tuple[ValidationErrorEntry, ...]
    exc.model          # type[Model]
    str(exc)           # rendered message
```

Each entry has:

- `loc`: a tuple of strings naming the location. For per-field
  validators this is `(field_name,)`; for cross-field axioms it is
  `()`.
- `type`: a discriminator string (`missing_required`, `extra_field`,
  `type_error`, `validates_failed`, `axiom_failed`).
- `msg`: a human-readable description.

The set of `type` values is open; new versions may add more.
