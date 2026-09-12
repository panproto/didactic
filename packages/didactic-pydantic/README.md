# didactic-pydantic

[![PyPI](https://img.shields.io/pypi/v/didactic-pydantic?style=flat-square&color=blue)](https://pypi.org/project/didactic-pydantic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-pydantic?style=flat-square)](https://pypi.org/project/didactic-pydantic/)
[![License](https://img.shields.io/pypi/l/didactic-pydantic?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/pydantic/)

`didactic-pydantic` converts models between `pydantic.BaseModel` and
`didactic.api.Model`. It adds the `didactic.pydantic` module and supports
applications that need both model systems during a migration.

## Install

```sh
pip install didactic-pydantic
```

The distribution depends on `didactic` and `pydantic>=2.10`.

## Convert a Pydantic model

`from_pydantic` creates a Didactic model class:

```python
from pydantic import BaseModel, Field

from didactic.pydantic import from_pydantic


class PydanticUser(BaseModel):
    id: str
    email: str = Field(description="Primary contact")


User = from_pydantic(PydanticUser)
user = User(id="u1", email="alice@example.com")
```

The conversion preserves annotations, defaults, factories, aliases,
descriptions, examples, deprecation flags, and `Annotated` constraint
metadata. Constraints from `annotated-types`, such as `Ge` and `Le`, become
Didactic axioms.

## Convert a Didactic model

`to_pydantic` creates a Pydantic model class:

```python
import didactic.api as dx
from didactic.pydantic import to_pydantic


class User(dx.Model):
    id: str
    email: str = dx.field(description="Primary contact")


PydanticUser = to_pydantic(User)
user = PydanticUser(id="u1", email="alice@example.com")
```

The adapter caches generated classes. Repeated calls with the same input class
return the same output class.

## Translation boundary

Pydantic field validators, model validators, computed fields, and discriminated
unions require corresponding Didactic definitions after conversion. They are
not copied by `from_pydantic`.

Didactic models with `dx.indexed_by` fields retain their cross-field checks in
the generated Pydantic class. Their JSON Schema also retains the conditional
cases associated with known indices.

## Documentation

See the [Pydantic interop guide](https://panproto.dev/didactic/guide/pydantic/)
for the conversion matrix and round-trip behavior.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
