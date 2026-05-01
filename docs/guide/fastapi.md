# FastAPI

The `didactic-fastapi` distribution adapts `dx.Model` types for use
as FastAPI request and response bodies. The current implementation
goes through `to_pydantic` and caches the result; no new
class-per-request work happens at runtime.

## Installation

```bash
pip install didactic-fastapi
```

The package contributes `didactic.fastapi` to the namespace and
depends on `fastapi>=0.115`.

## Using a Model in a route

```python
import didactic.api as dx
from fastapi import FastAPI
from didactic.fastapi import as_response


class User(dx.Model):
    id: str
    email: str


app = FastAPI()


@app.get("/users/{uid}", response_model=as_response(User))
def get_user(uid: str) -> User:
    return User(id=uid, email="ada@example.org")
```

`as_response(User)` returns a `pydantic.BaseModel` subclass that
mirrors `User`. FastAPI uses it for response validation and OpenAPI
generation. Each `dx.Model` is converted exactly once; subsequent
calls return the cached Pydantic class.

## Request bodies

`as_request` is a synonym of `as_response`. Use whichever name reads
naturally in your route signatures:

```python
from didactic.fastapi import as_request


@app.post("/users")
def create_user(payload: as_request(User)) -> User:
    return User(**payload.model_dump())
```

## Validation errors as 422 responses

Install the validation handler once:

```python
from didactic.fastapi import register_validation_handler

register_validation_handler(app)
```

After this, any `dx.ValidationError` raised inside a route surfaces
as a 422 response. The body shape mirrors FastAPI's own error
format:

```json
{
  "detail": [
    {"loc": ["email"], "msg": "...", "type": "validates_failed"}
  ]
}
```

Client code that already handles FastAPI's 422s sees the same shape.

## Caveats

- The adapter goes through `to_pydantic`. Models with computed or
  derived fields lose those fields on the Pydantic side; if you need
  them in the response, declare them on the Pydantic class instead
  (or move to plain Pydantic for that endpoint).
- The cache key is the `dx.Model` class identity. If you build Models
  dynamically per request, the cache will grow without bound; do the
  conversion once at startup and reuse.
