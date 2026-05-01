# Validation

didactic checks three things at construction time:

1. Each value satisfies its annotation (handled by the type
   translation layer).
2. Each `@validates`-decorated method returns ``True``.
3. Each entry in `__axioms__` evaluates to ``True`` against the
   field environment.

A failure in any of the three raises
[didactic.api.ValidationError][didactic.api.ValidationError] with one
[ValidationErrorEntry][didactic.api.ValidationErrorEntry] per failure.

## Per-field validators

Decorate a method with [@dx.validates][didactic.api.validates] to attach
a check to a named field:

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str

    @dx.validates("email")
    def _email_must_have_at(self, value: str) -> bool:
        return "@" in value
```

The validator runs after type translation. It receives the decoded
value and returns a `bool`. A return of ``False`` raises
`ValidationError`; raising directly from inside the validator works
too, in which case the raised exception is wrapped.

## Class-level axioms

Axioms are conditions on the field environment as a whole. Use them
when the rule depends on more than one field:

```python
class Range(dx.Model):
    low: int
    high: int

    __axioms__ = [
        dx.axiom("low >= 0", message="low must be non-negative"),
        dx.axiom("low <= high", message="low must not exceed high"),
    ]
```

Each axiom is parsed via `panproto.parse_expr` and evaluated
against `{field_name: decoded_value}` at construction time. Axioms
inherited from a base class are checked too.

The expression syntax is the panproto-Expr surface syntax: lambda
expressions, comparisons, boolean connectives, arithmetic, and a
small set of builtins. The most common forms (comparisons, `==`,
`/=`, `&&`, `||`, `not`, arithmetic) are listed in
[Guides > Axioms](../guide/axioms.md).

## Inspecting failures

A `ValidationError` carries a tuple of entries plus a reference to
the Model class:

```python
try:
    User(id="u1", email="not-an-email")
except dx.ValidationError as exc:
    for entry in exc.entries:
        print(entry.loc, entry.type, entry.msg)
    # ('email',) validates_failed `email` validator returned False
```

Per-entry types in v0.0.1: `missing_required`, `extra_field`,
`type_error`, `validates_failed`, `axiom_failed`. New types may be
added in subsequent releases; treat the set as open.

[Next: serialisation](04-serialisation.md).
