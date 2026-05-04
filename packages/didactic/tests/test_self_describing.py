"""Tests for self-describing JSON via fingerprint URIs."""

# Test passes a ``dict[str, str]`` to ``validate_with_uri_lookup``
# whose signature is ``JsonObject``; the runtime accepts the subtype.
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import JsonObject


class SDUser(dx.Model):
    id: str
    email: str


# -- schema_uri -------------------------------------------------------


def test_schema_uri_is_didactic_v1() -> None:
    uri = dx.schema_uri(SDUser)
    assert uri.startswith("didactic://v1/")
    # the suffix is the structural fingerprint (64 hex chars)
    fp = uri[len("didactic://v1/") :]
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_schema_uri_stable_for_same_class() -> None:
    assert dx.schema_uri(SDUser) == dx.schema_uri(SDUser)


def test_schema_uri_structural_equivalence() -> None:
    """Two structurally identical Models share a schema URI."""

    class Other(dx.Model):
        id: str
        email: str

    assert dx.schema_uri(SDUser) == dx.schema_uri(Other)


# -- embed_schema_uri -------------------------------------------------


def test_embed_schema_uri_prepends_uri() -> None:
    u = SDUser(id="u1", email="ada@example.org")
    payload = dx.embed_schema_uri(u)
    assert payload["$schema"] == dx.schema_uri(SDUser)
    assert payload["id"] == "u1"
    assert payload["email"] == "ada@example.org"


# -- FingerprintRegistry ---------------------------------------------


def test_registry_register_and_lookup() -> None:
    reg = dx.FingerprintRegistry()
    reg.register(SDUser)
    assert SDUser in reg
    assert dx.schema_uri(SDUser) in reg


def test_registry_lookup_unknown_uri() -> None:
    reg = dx.FingerprintRegistry()
    assert reg.lookup("didactic://v1/0" * 16) is None


def test_registry_returns_self_from_register() -> None:
    """register returns the class for fluent chaining."""
    reg = dx.FingerprintRegistry()
    cls = reg.register(SDUser)
    assert cls is SDUser


def test_registry_len() -> None:
    reg = dx.FingerprintRegistry()
    assert len(reg) == 0
    reg.register(SDUser)
    assert len(reg) == 1


# -- validate_with_uri_lookup ----------------------------------------


def test_validate_round_trip() -> None:
    reg = dx.FingerprintRegistry()
    reg.register(SDUser)
    u = SDUser(id="u1", email="ada@example.org")
    payload = dx.embed_schema_uri(u)
    back = dx.validate_with_uri_lookup(payload, reg)
    assert back == u


def test_validate_missing_schema_key_raises() -> None:
    reg = dx.FingerprintRegistry()
    with pytest.raises(KeyError, match="\\$schema"):
        dx.validate_with_uri_lookup({"id": "u1"}, reg)


def test_validate_unknown_uri_raises() -> None:
    reg = dx.FingerprintRegistry()
    payload: JsonObject = {"$schema": "didactic://v1/" + "0" * 64, "id": "u1"}
    with pytest.raises(LookupError, match="no registered model"):
        dx.validate_with_uri_lookup(payload, reg)
