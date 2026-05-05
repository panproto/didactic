# Generic Models

A `dx.Model` subclass declared with type parameters synthesises a
concrete subclass on subscript. `Range[int](min=0, max=10)` produces
an instance of `Range[int]`, a real subclass cached per type-arg
tuple, with the parent's `T`-typed fields rewritten to use `int`.

## Declaring a generic Model

PEP 695 syntax (recommended):

```python
import didactic.api as dx


class Range[T: int | float](dx.Model):
    min: T
    max: T
```

Legacy `Generic[T]` mixin syntax also works:

```python
from typing import Generic, TypeVar


T = TypeVar("T", int, float)


class Range(dx.Model, Generic[T]):
    min: T
    max: T
```

## Subscripting

```python
IntRange = Range[int]
IntRange(min=0, max=10)
# Range[int](min=0, max=10)
```

`Range[int]` returns a real subclass of `Range`. Repeated subscripts
return the same class object:

```python
Range[int] is Range[int]   # True
Range[int].__theory__      # built once, cached
```

The synthesised class participates in everything an explicit subclass
would: `model_dump()`, `model_validate_json()`, lenses, axioms,
codegen, `Repository.add(...)`. Its `__field_specs__` carries
concrete sorts (e.g. `Int` for `int`, not the deferred `_TypeVar:T`
placeholder).

## Defaults and metadata propagate

Defaults on the generic carry through to the synthesised subclass:

```python
class Range[T: int | float](dx.Model):
    min: T = 0
    max: T = 100


Range[int]()
# Range[int](min=0, max=100)
```

`dx.field(...)` metadata also propagates: `default`,
`default_factory`, `description`, `alias`, `examples`, `deprecated`,
`nominal`, `usage_mode`, `extras`, and `converter` all flow onto the
synthesised subclass's spec.

```python
class Counter[T](dx.Model):
    value: T = dx.field(default=0, description="a counter")


Counter[int].__field_specs__["value"].description
# 'a counter'
```

## Substitution through nested shapes

The substitution walks through the common generic containers,
unions, and `Annotated[...]`:

```python
from typing import Annotated
from annotated_types import Ge


class Items[T](dx.Model):
    seq: tuple[T, ...] = ()
    by_name: dict[str, T] = dx.field(default_factory=dict)
    maybe: T | None = None
    bounded: Annotated[T, Ge(0)] = 0
```

Each is rewritten correctly under subscript:

| declared | after `Items[int]` |
| --- | --- |
| `tuple[T, ...]` | `tuple[int, ...]` |
| `dict[str, T]` | `dict[str, int]` |
| `T \| None` | `int \| None` |
| `Annotated[T, Ge(0)]` | `Annotated[int, Ge(0)]` |

The `Annotated[...]` metadata is preserved verbatim, so the
``annotated-types`` axioms (`Ge`, `Le`, `MinLen`, etc.) continue to
fire on the synthesised subclass.

## Multiple type parameters

```python
class Pair[K, V](dx.Model):
    key: K
    value: V


Pair[str, int](key="x", value=42)
# Pair[str, int](key='x', value=42)
```

Arity must match: `Pair[int]` raises `TypeError`.

## Subclassing a parameterised generic

```python
class IntTree(Range[int]):
    label: str
```

`Range[int]` is a real class, so `IntTree` subclasses it normally.
`IntTree.__field_specs__` contains `min`, `max`, and `label`.

## What stays unsubstituted

A bare `dx.Model` subclass passed as a type argument is not
auto-wrapped in `Embed[T]` or `Ref[T]`. If you want the generic to
hold an embedded sub-model, declare it explicitly:

```python
class Container[T](dx.Model):
    item: dx.Embed[T]


class Person(dx.Model):
    name: str


Container[Person](item=Person(name="alice"))
```

`Container[Person]` substitutes `Embed[T]` to `Embed[Person]`.

## Constructing the unparameterised generic

Constructing the bare generic without subscripting raises:

```python
Range(min=0, max=10)
# ValidationError: cannot encode a TypeVar-annotated field; the class
# is generic and must be parameterised before construction
```

The TypeVar guards on the original class stay in place; only the
synthesised subclass has concrete sorts.

## TypeVar constraints

`TypeVar("T", int, float)` is enforced statically by your type checker
but not at didactic runtime. `Range[str]` synthesises a class whose
`min` field has sort `String`; the TypeVar's static `int | float`
constraint is information for the type checker, not a runtime guard.

## Cache lifetime

The cache lives on the generic class as `__parameterised_cache__`. A
synthesised subclass is held alive by the cache for as long as the
generic class itself is reachable; if the generic class is garbage
collected, the cache (and every entry) goes with it.
