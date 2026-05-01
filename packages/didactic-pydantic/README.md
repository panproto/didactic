# didactic-pydantic

*Bidirectional adapter between `pydantic.BaseModel` and `dx.Model`.*

[![PyPI](https://img.shields.io/pypi/v/didactic-pydantic?style=flat-square&color=blue)](https://pypi.org/project/didactic-pydantic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-pydantic?style=flat-square)](https://pypi.org/project/didactic-pydantic/)
[![License](https://img.shields.io/pypi/l/didactic-pydantic?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/pydantic/)

Contributes `didactic.pydantic` to the namespace package.

## Install

```sh
pip install didactic-pydantic
```

The package depends on `didactic` and `pydantic>=2.10`.

## Quickstart

`from_pydantic` converts a `pydantic.BaseModel` subclass into a
`dx.Model` subclass:

```python
from pydantic import BaseModel, Field
from didactic.pydantic import from_pydantic


class PydUser(BaseModel):
    id: str
    email: str = Field(description="primary contact")


User = from_pydantic(PydUser)
```

Field annotations, defaults, factories, aliases, descriptions,
examples, and the `deprecated` flag carry across.
`Annotated[T, ...]` constraint metadata flows through unchanged, so
`annotated-types` primitives (`Ge`, `Le`, ...) continue to produce
axioms on the didactic side.

Custom Pydantic validators (`@field_validator`, `@model_validator`),
`@computed_field`, and discriminated unions are not translated; the
[Pydantic interop guide](https://panproto.dev/didactic/guide/pydantic/)
lists the didactic-side replacements.

`to_pydantic` is the inverse direction:

```python
import didactic.api as dx
from didactic.pydantic import to_pydantic


class User(dx.Model):
    id: str
    email: str = dx.field(description="primary contact")


PydUser = to_pydantic(User)
```

Use `to_pydantic` to expose a `dx.Model` to FastAPI, OpenAPI
generators, or any other Pydantic-shaped tool. The conversion is
cached, so repeated calls with the same input return the same
Pydantic class.

## Documentation

See [Guides > Pydantic interop](https://panproto.dev/didactic/guide/pydantic/)
for the full feature matrix and round-trip behaviour.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
