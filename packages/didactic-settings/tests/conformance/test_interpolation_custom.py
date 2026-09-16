"""Custom resolver registration."""

from __future__ import annotations

import pytest

from didactic.settings import (
    list_resolvers,
    register_resolver,
    resolve,
    unregister_resolver,
)


def _upper(s: str) -> str:
    return s.upper()


def _echo(s: str) -> str:
    return s


def _shout(s: str) -> str:
    return s + "!"


def _suffix_a(s: str) -> str:
    return s + "a"


def _suffix_b(s: str) -> str:
    return s + "b"


def test_register_and_use() -> None:
    register_resolver("test.upper", _upper, replace=True)
    try:
        assert resolve("${test.upper:hello}", root={}) == "HELLO"
        assert "test.upper" in list_resolvers()
    finally:
        unregister_resolver("test.upper")


def test_register_existing_without_replace_raises() -> None:
    register_resolver("test.echo", _echo, replace=True)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_resolver("test.echo", _shout)
    finally:
        unregister_resolver("test.echo")


def test_register_replace_ok() -> None:
    register_resolver("test.x", _suffix_a, replace=True)
    register_resolver("test.x", _suffix_b, replace=True)
    try:
        assert resolve("${test.x:y}", root={}) == "yb"
    finally:
        unregister_resolver("test.x")


def test_unregister_unknown_is_noop() -> None:
    unregister_resolver("test.never_registered")
