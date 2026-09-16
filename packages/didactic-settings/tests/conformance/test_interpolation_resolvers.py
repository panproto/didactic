"""Built-in resolver behaviour: oc.env, oc.decode, etc."""

from __future__ import annotations

import base64
import os

import pytest

from didactic.settings import InterpolationError, resolve


def test_oc_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEAD_TEST_VAR", "hello")
    assert resolve("${oc.env:BEAD_TEST_VAR}", root={}) == "hello"


def test_oc_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEAD_TEST_VAR", raising=False)
    assert resolve("${oc.env:BEAD_TEST_VAR,fallback}", root={}) == "fallback"


def test_oc_env_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEAD_TEST_VAR", raising=False)
    with pytest.raises(InterpolationError, match="not set"):
        resolve("${oc.env:BEAD_TEST_VAR}", root={})


def test_oc_decode_base64() -> None:
    encoded = base64.b64encode(b"secret").decode("ascii")
    assert resolve(f"${{oc.decode:{encoded}}}", root={}) == "secret"


def test_oc_decode_unknown_encoding() -> None:
    with pytest.raises(InterpolationError, match="unknown encoding"):
        resolve("${oc.decode:foo,rot13}", root={})


def test_unknown_resolver() -> None:
    with pytest.raises(InterpolationError, match="Unknown resolver"):
        resolve("${nope:x}", root={})


def test_resolver_arg_is_interpolated() -> None:
    """Resolver arguments themselves resolve before the resolver runs."""
    os.environ["BEAD_T_NAME"] = "WORLD"
    try:
        root = {"key": "BEAD_T_NAME"}
        assert resolve("${oc.env:${key}}", root=root) == "WORLD"
    finally:
        os.environ.pop("BEAD_T_NAME", None)
