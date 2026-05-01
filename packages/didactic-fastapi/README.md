# didactic-fastapi

FastAPI integration for `dx.Model` types. Contributes
`didactic.fastapi` to the namespace package.

## Install

```sh
pip install didactic-fastapi
```

The package depends on `didactic`, `didactic-pydantic`, and
`fastapi>=0.115`.

## Usage

```python
import didactic.api as dx
from fastapi import FastAPI
from didactic.fastapi import as_response, register_validation_handler


class User(dx.Model):
    id: str
    email: str


app = FastAPI()
register_validation_handler(app)


@app.get("/users/{uid}", response_model=as_response(User))
def get_user(uid: str) -> User:
    return User(id=uid, email="ada@example.org")
```

`as_response(model)` returns a `pydantic.BaseModel` subclass
mirroring the input `dx.Model`. FastAPI uses the result for response
validation and OpenAPI generation. The conversion is cached per input
class.

`as_request(model)` is a synonym; use whichever name reads naturally
in your route signatures.

`register_validation_handler(app)` installs an exception handler so
that `dx.ValidationError` raised inside a route surfaces as a 422
response shaped like FastAPI's own validation errors.

## Documentation

See [Guides > FastAPI](https://panproto.dev/didactic/guide/fastapi/)
for the full integration guide and caveats.

## License

MIT.
