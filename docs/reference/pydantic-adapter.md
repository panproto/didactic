# Pydantic adapter

The Pydantic adapters live in the `didactic-pydantic` sibling
distribution under the `didactic.pydantic` namespace.

## `from_pydantic`

```python
from didactic.pydantic import from_pydantic
```

Convert a Pydantic v2 ``BaseModel`` subclass to a `dx.Model` subclass.
See the [Pydantic interop guide](../guide/pydantic.md) for usage and
examples.

## `to_pydantic`

```python
from didactic.pydantic import to_pydantic
```

The inverse direction: convert a `dx.Model` to a Pydantic
``BaseModel`` for use with FastAPI / OpenAPI consumers. See the
guide for details.
