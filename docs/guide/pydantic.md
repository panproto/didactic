# Pydantic interop

The `didactic-pydantic` distribution provides two adapters for moving
Models between didactic and Pydantic v2.

## Installation

```bash
pip install didactic-pydantic
```

The package contributes `didactic.pydantic` to the namespace.

## from_pydantic

Convert a `pydantic.BaseModel` subclass into a `dx.Model` subclass:

```python
from pydantic import BaseModel, Field
from didactic.pydantic import from_pydantic


class PydUser(BaseModel):
    id: str
    email: str = Field(description="primary contact")


User = from_pydantic(PydUser)        # dx.Model subclass
u = User(id="u1", email="a@b.c")
```

Metadata that survives:

- field annotations, including `Annotated[T, ...]` constraint
  metadata (`Ge`, `Le`, `MinLen`, ...)
- defaults and factories
- aliases (`alias`, `validation_alias`, `serialization_alias`
  collapse to a single `alias`)
- descriptions, examples
- the `deprecated` flag
- `json_schema_extra` lands under `dx.field(extras=...)`

Pydantic features that do not flow across:

- `@field_validator` and `@model_validator` methods. Re-author with
  [@dx.validates][didactic.api.validates] (per-field) or
  [__axioms__](axioms.md) (cross-field).
- `@computed_field`. Re-author with [@dx.computed][didactic.api.computed]
  or [@dx.derived][didactic.api.derived].
- Discriminated unions. Re-author as
  [dx.TaggedUnion](unions.md).

## to_pydantic

The inverse direction. Use it to expose a `dx.Model` to FastAPI,
OpenAPI generators, or any other Pydantic-shaped tool:

```python
import didactic.api as dx
from didactic.pydantic import to_pydantic


class User(dx.Model):
    id: str
    email: str = dx.field(description="primary contact")


PydUser = to_pydantic(User)          # pydantic.BaseModel subclass
PydUser(id="u1", email="a@b.c")
```

The conversion is cached: a second call with the same input class
returns the same Pydantic class.

## Round-tripping

`from_pydantic(to_pydantic(M))` and `to_pydantic(from_pydantic(P))`
both round-trip the cross-format-stable metadata exactly. Computed
fields and discriminated unions are dropped on the
`dx.Model -> Pydantic` direction; everything else survives.
