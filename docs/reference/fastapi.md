# FastAPI

The `didactic-fastapi` distribution.

```python
from didactic.fastapi import (
    as_request,
    as_response,
    register_validation_handler,
)
```

## `as_request(model)`

Return the Pydantic adapter for use as a FastAPI request body type.
The conversion is cached, so repeated calls with the same input
return the same Pydantic class.

## `as_response(model)`

Synonym of `as_request`. Use whichever name reads naturally in your
route signatures.

## `register_validation_handler(app)`

Install an exception handler on `app` that turns
`dx.ValidationError` into a 422 response shaped like FastAPI's own
validation errors.

For usage examples, see [Guides > FastAPI](../guide/fastapi.md).
