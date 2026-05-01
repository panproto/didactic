"""didactic-fastapi: FastAPI integration for didactic Models.

Top-level surface:

[as_request][didactic.fastapi.as_request]
    Wrap a [didactic.api.Model][didactic.api.Model] as a FastAPI-friendly
    request body type. Calls
    [didactic.pydantic.to_pydantic][didactic.pydantic.to_pydantic]
    under the hood.
[as_response][didactic.fastapi.as_response]
    The same conversion for response models. Synonymous with
    [as_request][didactic.fastapi.as_request]; provided as a
    separate name so route signatures read naturally.
[register_validation_handler][didactic.fastapi.register_validation_handler]
    Install an exception handler that turns
    [didactic.api.ValidationError][didactic.api.ValidationError] into a 422
    response shaped like FastAPI's own validation errors.
"""

from didactic.fastapi._adapter import (
    as_request,
    as_response,
    register_validation_handler,
)

__version__ = "0.3.1"

__all__ = [
    "__version__",
    "as_request",
    "as_response",
    "register_validation_handler",
]
