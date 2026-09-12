# didactic-fastapi

[![PyPI](https://img.shields.io/pypi/v/didactic-fastapi?style=flat-square&color=blue)](https://pypi.org/project/didactic-fastapi/)
[![Python](https://img.shields.io/pypi/pyversions/didactic-fastapi?style=flat-square)](https://pypi.org/project/didactic-fastapi/)
[![License](https://img.shields.io/pypi/l/didactic-fastapi?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/guide/fastapi/)

`didactic-fastapi` adapts `dx.Model` classes for FastAPI request validation,
response validation, and OpenAPI generation. It adds the `didactic.fastapi`
module and uses `didactic-pydantic` at the framework boundary.

## Install

```sh
pip install didactic-fastapi
```

The distribution depends on `didactic`, `didactic-pydantic`, and
`fastapi>=0.115`.

## Use a Didactic response model

```python
import didactic.api as dx
from didactic.fastapi import as_response, register_validation_handler
from fastapi import FastAPI


class User(dx.Model):
    id: str
    email: str


app = FastAPI()
register_validation_handler(app)


@app.get("/users/{user_id}", response_model=as_response(User))
def get_user(user_id: str) -> User:
    return User(id=user_id, email="ada@example.org")
```

`as_response(User)` returns a cached `pydantic.BaseModel` subclass that mirrors
`User`. FastAPI uses that class for validation and OpenAPI generation.

## Adapter behavior

| Function | Behavior |
| --- | --- |
| `as_response(model)` | returns the generated Pydantic class for a response model |
| `as_request(model)` | returns the same adapter under a request-oriented name |
| `register_validation_handler(app)` | converts `dx.ValidationError` raised in a route into a FastAPI-style 422 response |

Models with `dx.indexed_by` fields retain their cross-field validation. Their
known index cases also appear as conditional constraints in the generated
OpenAPI schema.

## Documentation

See the [FastAPI guide](https://panproto.dev/didactic/guide/fastapi/) for request
models, response models, error handling, and integration limits.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
