# Validators

[didactic.api.validates][didactic.api.validates] decorates a method as
a per-field check that runs at construction time and on
[`with_(...)`][didactic.api.Model.with_]:

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str

    @dx.validates("email")
    def _check_email(self, value: str) -> str:
        if "@" not in value:
            raise ValueError("missing '@'")
        return value.lower()
```

A validator receives the field value and **returns the value to
store** (possibly modified). To reject the input, `raise ValueError`
or `raise TypeError`; the failure is collected as a
`ValidationError` entry with `type="validator_error"` and
`loc=(field_name,)`.

## ``before`` and ``after``

`@validates` accepts a `mode` argument:

- ``mode="after"`` (the default) runs after the encoder has
  type-validated the input. The validator sees the canonical
  decoded form: a `tuple` for `tuple[T, ...]` fields, a `frozenset`
  for `frozenset[T]` fields, and so on. Its return value is
  re-encoded if it differs from the input.
- ``mode="before"`` runs *before* the encoder, on the raw user input
  (after any `dx.field(converter=...)` has already run). Use this
  for normalisation that should happen before the type check, e.g.
  lowercasing a string to compare against a `Literal`.

```python
class Email(dx.Model):
    address: str

    @dx.validates("address", mode="before")
    def _lower(self, value: str) -> str:
        return value.lower()
```

## Method shapes

The decorator works on instance methods, `@classmethod`, and
`@staticmethod`. The Model is frozen and not yet constructed when
validators run, so there is no instance ``self``. Instance methods
receive the **class** as their first argument:

```python
class M(dx.Model):
    name: str

    @dx.validates("name")
    def _strip(cls, value: str) -> str:   # name `cls` is conventional
        return value.strip()

    @dx.validates("name")
    @classmethod
    def _check_nonempty(cls, value: str) -> str:
        if not value:
            raise ValueError("empty")
        return value

    @dx.validates("name")
    @staticmethod
    def _trim(value: str) -> str:
        return value.strip()
```

## Multiple fields share a validator

```python
class Pair(dx.Model):
    first: str
    last: str

    @dx.validates("first", "last")
    def _strip(cls, value: str) -> str:
        return value.strip()
```

## Multiple validators per field

Multiple `@validates` methods on the same field run in declaration
order, threading the value through. The first one to raise
short-circuits the chain for that field.

```python
class Word(dx.Model):
    text: str

    @dx.validates("text")
    def _strip(cls, v: str) -> str:
        return v.strip()

    @dx.validates("text")
    def _upper(cls, v: str) -> str:
        return v.upper()
```

## Inheritance

Subclasses inherit their parent's validators. To **override** an
inherited validator, redeclare the method *with* `@validates`:

```python
class Base(dx.Model):
    name: str

    @dx.validates("name")
    def _strip(cls, v: str) -> str:
        return v.strip()


class Loud(Base):
    @dx.validates("name")
    def _strip(cls, v: str) -> str:
        return v.strip().upper()
```

A subclass that shadows the method *without* `@validates` is treated
as a deliberate disable: the inherited marker is dropped and the
field skips validation.

## Cross-field invariants

`@validates` runs against one field at a time. For a check that
spans multiple fields, prefer an [axiom](axioms.md) when the
constraint is expressible in the surface syntax:

```python
class Range(dx.Model):
    low: int
    high: int

    __axioms__ = [dx.axiom("low <= high")]
```

When the check needs Python (cross-collection consistency, length
matching across two optional fields, anything that can't be cleanly
written as an axiom expression), use `@dx.model_validator()`. The
decorated method receives the constructed instance and may
`raise ValueError` / `raise TypeError` to reject it; failures
surface as `ValidationError` entries with `type="validator_error"`
and an empty `loc`:

```python
import didactic.api as dx


class Rules(dx.Model):
    binary_rules: tuple[str, ...] = ()
    binary_weights: tuple[float, ...] | None = None

    @dx.model_validator()
    def _check_lengths(self) -> "Rules":
        if self.binary_weights is not None and len(self.binary_weights) != len(
            self.binary_rules
        ):
            raise ValueError(
                "binary_weights length must match binary_rules length"
            )
        return self
```

Class-level validators run *after* every per-field `@validates` and
every `__axioms__` check have passed. Multiple `@model_validator`
methods on the same class run in declaration order; failures from
all of them are collected into a single `ValidationError`. Subclass
inheritance and silent-shadow disable work the same as for
`@validates`.

`mode="before"` is reserved for a future pre-construction hook;
only `mode="after"` (the default) is currently accepted.

## Validators do not travel with the Theory

`@validates`-decorated methods live on the Python side only; they are
**not** lifted into the panproto Theory. Constraints expressed as
`Annotated[T, ...]` metadata or as `__axioms__` *are* lifted.
Choose the axiom path when you want the constraint to travel
cross-language with the Theory.

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

- `loc`: a tuple naming the location. For per-field validators this
  is `(field_name,)`; for cross-field axioms it is `()`.
- `type`: a discriminator string. `validator_error` means a
  `@validates` method raised; `type_error` means the encoder
  rejected the value; `axiom_violation` means an `__axioms__`
  expression failed; `missing_required`, `extra_field`, and
  `converter_error` cover the other construction-time failures.
- `msg`: a human-readable description (the exception message for
  validator errors).

The set of `type` values is open; new versions may add more.
