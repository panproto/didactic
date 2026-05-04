"""didactic Model -> FastAPI route adapter.

The adapter is a thin layer over
[didactic.pydantic.to_pydantic][didactic.pydantic.to_pydantic]: each
``dx.Model`` is converted to a Pydantic ``BaseModel`` once, cached,
and reused on every request. The cache is keyed by the source class
so the conversion only happens once per Model regardless of how many
routes reference it.

See Also
--------
didactic.pydantic.to_pydantic : the underlying converter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from didactic.pydantic import to_pydantic

if TYPE_CHECKING:
    from pydantic import BaseModel

    import didactic.api as dx
    from fastapi import FastAPI

# cache the conversion so each Model maps to the same Pydantic class
_CACHE: dict[type, type] = {}


def as_request[M: dx.Model](model: type[M]) -> type[BaseModel]:
    """Return the Pydantic adapter for use as a FastAPI request body type.

    Parameters
    ----------
    model
        A [didactic.api.Model][didactic.api.Model] subclass.

    Returns
    -------
    type
        A Pydantic ``BaseModel`` subclass mirroring ``model``'s shape.
        Cached: subsequent calls with the same ``model`` return the
        same class.
    """
    if model not in _CACHE:
        _CACHE[model] = to_pydantic(model)
    return _CACHE[model]


def as_response[M: dx.Model](model: type[M]) -> type[BaseModel]:
    """Synonym of [as_request][didactic.fastapi.as_request].

    Provided as a separate name so route signatures read naturally
    (``response_model=as_response(User)``).
    """
    return as_request(model)


def register_validation_handler(app: FastAPI) -> None:
    """Install a 422 handler for ``dx.ValidationError``.

    Parameters
    ----------
    app
        The FastAPI application to attach the handler to.

    Notes
    -----
    The response shape mirrors FastAPI's own validation-error format,
    so existing clients see no change. didactic's per-error
    ``loc``/``type``/``msg`` map onto FastAPI's identical names.
    """
    import didactic.api as dx_module  # noqa: PLC0415
    from fastapi import Request  # noqa: PLC0415
    from fastapi.responses import JSONResponse  # noqa: PLC0415

    # ``_handler`` is registered with the app via the decorator side
    # effect; the local binding is not used directly afterwards. The
    # explicit ``del`` makes the intent obvious and silences pyright's
    # ``reportUnusedFunction`` warning.
    @app.exception_handler(dx_module.ValidationError)
    async def _handler(_: Request, exc: dx_module.ValidationError) -> JSONResponse:
        body = {
            "detail": [
                {"loc": list(entry.loc), "msg": entry.msg, "type": entry.type}
                for entry in exc.entries
            ],
        }
        return JSONResponse(status_code=422, content=body)

    del _handler


__all__ = [
    "as_request",
    "as_response",
    "register_validation_handler",
]
