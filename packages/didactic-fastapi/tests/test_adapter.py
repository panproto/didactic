"""Tests for didactic-fastapi."""

# Pydantic ``BaseModel`` instance returned by ``as_request`` exposes
# fields dynamically; pyright can't see them.
# Tracked in panproto/didactic#1.
# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false

from __future__ import annotations

import didactic.api as dx
from didactic.fastapi import as_request, as_response


class User(dx.Model):
    id: str
    email: str


def test_as_request_returns_pydantic_class() -> None:
    from pydantic import BaseModel

    Pyd = as_request(User)
    assert issubclass(Pyd, BaseModel)
    instance = Pyd(id="u1", email="ada@example.org")
    assert instance.id == "u1"


def test_as_request_caches_by_class() -> None:
    a = as_request(User)
    b = as_request(User)
    assert a is b


def test_as_response_alias_returns_same_class() -> None:
    assert as_response(User) is as_request(User)


def test_validation_handler_installation() -> None:
    """register_validation_handler is callable on a real FastAPI app."""
    from fastapi import FastAPI

    from didactic.fastapi import register_validation_handler

    app = FastAPI()
    register_validation_handler(app)
    # the handler should now be present in app.exception_handlers
    assert dx.ValidationError in app.exception_handlers
