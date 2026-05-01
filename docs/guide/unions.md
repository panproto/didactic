# Tagged unions

`dx.TaggedUnion` is the discriminated-union type. Each variant is a
real subclass and carries a `Literal` discriminator, so dispatch on
`model_validate` is by string tag.

```python
import didactic.api as dx
from typing import Literal


class Shape(dx.TaggedUnion, discriminator="kind"):
    kind: str


class Circle(Shape):
    kind: Literal["circle"] = "circle"
    radius: float


class Square(Shape):
    kind: Literal["square"] = "square"
    side: float
```

The base class declares the discriminator field name. Each variant
narrows the discriminator to a single literal value.

## Construction

Each variant is a real class, so direct construction works:

```python
c = Circle(radius=3.0)
s = Square(side=2.0)
```

## Validation

`Shape.model_validate` dispatches on the discriminator:

```python
c2 = Shape.model_validate({"kind": "circle", "radius": 5.0})
isinstance(c2, Circle)        # True
```

A payload whose discriminator does not match any registered variant
raises a `ValidationError`.

## Listing variants

Every `TaggedUnion` subclass exposes its variants:

```python
Shape.__variants__
# {'circle': <class 'Circle'>, 'square': <class 'Square'>}
```

This is the surface code-generation tools and schema-diff tools read
when emitting the union.

## Limitations

Discriminator values must be string literals. Non-string discriminators
(integer kinds, enum members) are not currently supported; if you
need that, model the discriminator field as a `Literal["a", "b"]`
typed `str`.
