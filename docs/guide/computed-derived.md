# Computed and derived fields

Two decorators turn methods into output-only fields:

| decorator | recomputes... | stored | included in `model_dump` |
| --- | --- | --- | --- |
| `@dx.computed` | every read | no | yes |
| `@dx.derived` | once at construction | yes (per instance) | yes |

Both decorators turn a zero-argument method (other than `self`) into
a property the user reads with normal attribute access.

## `@dx.computed`

Use `@computed` when the function is cheap to call and the value is
naturally a function of the current field values:

```python
import didactic.api as dx


class Person(dx.Model):
    first: str
    last: str

    @dx.computed
    def full_name(self) -> str:
        return f"{self.first} {self.last}"


p = Person(first="Ada", last="Lovelace")
p.full_name
# 'Ada Lovelace'
p.model_dump()["full_name"]
# 'Ada Lovelace'
```

Because Models are frozen, the returned value is always the same on
repeated reads of the same instance. `@computed` does no caching of
its own, so each access calls the decorated function. For pure
functions of the inputs this is fine; for expensive ones, prefer
`@derived`.

## `@dx.derived`

Use `@derived` when the computation is expensive or has any side
effect that should run exactly once:

```python
class Box(dx.Model):
    w: int
    h: int

    @dx.derived
    def area(self) -> int:
        return self.w * self.h


b = Box(w=3, h=4)
b.area      # 12 (computed once and cached)
b.area      # 12 (returned from cache)
```

The cache lives on a per-instance slot (`_derived_cache`) and is
populated lazily on first access. After construction the value is
fixed for the lifetime of the instance.

Derived fields participate in `model_dump` exactly like computed
fields. Round-tripping a payload through `model_validate(model_dump(...))`
recovers a Model whose derived field re-evaluates to the same value.

## Choosing between the two

- A field that summarises immediate state and is cheap to compute
  (concatenation, arithmetic on tuples) belongs in `@computed`.
- A field that involves anything more (file reads, network calls,
  large structural traversals) belongs in `@derived`.
- A field that mutates external state belongs in neither; use a
  separate non-Model class for state machines.
