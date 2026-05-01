"""Smoke tests for the Model base class.

Notes
-----
These tests deliberately do NOT use ``from __future__ import annotations``
so we exercise the modern PEP 649 path through the metaclass. A separate
test module (``test_model_legacy.py``) exercises the future-import path.
"""

# Tests use ``Model.__class__(name, bases, namespace)`` to dynamically
# construct Model subclasses; pyright can't follow the metaclass
# invocation. Tracked in panproto/didactic#1.
# pyright: reportCallIssue=false, reportAttributeAccessIssue=false

from typing import Annotated

import pytest
from annotated_types import Ge

import didactic.api as dx


# A representative scalar-only model used across the suite.
class User(dx.Model):
    """Simple test model — three primitive fields."""

    id: str
    email: str
    display_name: str = ""


class Account(dx.Model):
    """Test model with optional and numeric fields."""

    id: str
    balance: int = 0
    nickname: str | None = None


class WithAxioms(dx.Model):
    """Test model with Annotated refinements."""

    age: Annotated[int, Ge(0)]


# -- field-spec collection -------------------------------------------------


def test_user_field_specs_present() -> None:
    specs = User.__field_specs__
    assert set(specs) == {"id", "email", "display_name"}
    assert specs["display_name"].default == ""


def test_user_schema_kind() -> None:
    assert User.__schema_kind__ == "User"


def test_required_fields_detected() -> None:
    specs = User.__field_specs__
    assert specs["id"].is_required
    assert specs["email"].is_required
    assert not specs["display_name"].is_required


# -- construction ----------------------------------------------------------


def test_construct_required_only() -> None:
    u = User(id="u1", email="a@b.c")
    assert u.id == "u1"
    assert u.email == "a@b.c"
    assert u.display_name == ""


def test_construct_with_default_overridden() -> None:
    u = User(id="u1", email="a@b.c", display_name="Alice")
    assert u.display_name == "Alice"


def test_missing_required_raises_validation_error() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        User(id="u1")
    assert any(e.type == "missing_required" for e in exc.value.entries)


def test_unknown_field_raises_validation_error() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        User(id="u1", email="a@b.c", bogus="x")
    assert any(e.type == "extra_field" for e in exc.value.entries)


def test_multiple_errors_collected() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        User(bogus="x")
    types = {e.type for e in exc.value.entries}
    # both missing-required and extra-field surface
    assert "missing_required" in types
    assert "extra_field" in types


# -- attribute access ------------------------------------------------------


def test_attribute_lookup_unknown() -> None:
    u = User(id="u1", email="a@b.c")
    with pytest.raises(AttributeError):
        _ = u.bogus


# -- immutability ----------------------------------------------------------


def test_models_are_frozen() -> None:
    u = User(id="u1", email="a@b.c")
    with pytest.raises(AttributeError):
        u.email = "other@example.com"


def test_with_returns_new_instance() -> None:
    u = User(id="u1", email="a@b.c")
    u2 = u.with_(email="new@b.c")
    assert u.email == "a@b.c"
    assert u2.email == "new@b.c"
    assert u is not u2


def test_with_unknown_field_raises() -> None:
    u = User(id="u1", email="a@b.c")
    with pytest.raises(dx.ValidationError):
        u.with_(bogus=1)


# -- serialisation ---------------------------------------------------------


def test_model_dump_round_trip() -> None:
    u = User(id="u1", email="a@b.c", display_name="Alice")
    payload = u.model_dump()
    assert payload == {"id": "u1", "email": "a@b.c", "display_name": "Alice"}
    u2 = User.model_validate(payload)
    assert u == u2


# -- equality / hash / repr ------------------------------------------------


def test_equality() -> None:
    u1 = User(id="u1", email="a@b.c")
    u2 = User(id="u1", email="a@b.c")
    assert u1 == u2
    assert hash(u1) == hash(u2)


def test_inequality() -> None:
    assert User(id="u1", email="a@b.c") != User(id="u2", email="a@b.c")
    assert User(id="u1", email="a@b.c") != "u1"


def test_repr() -> None:
    u = User(id="u1", email="a@b.c", display_name="A")
    r = repr(u)
    assert r.startswith("User(")
    assert "id='u1'" in r
    assert "email='a@b.c'" in r


# -- optional / numeric fields --------------------------------------------


def test_account_default_balance() -> None:
    a = Account(id="acc1")
    assert a.balance == 0
    assert a.nickname is None


def test_account_with_optional_set() -> None:
    a = Account(id="acc1", nickname="primary")
    assert a.nickname == "primary"


def test_account_with_change() -> None:
    a = Account(id="acc1")
    a2 = a.with_(balance=100, nickname="primary")
    assert a2.balance == 100
    assert a2.nickname == "primary"


# -- annotated -------------------------------------------------------------


def test_annotated_field_specs_carry_axioms() -> None:
    spec = WithAxioms.__field_specs__["age"]
    assert any("x >= 0" in a for a in spec.axioms)


def test_annotated_field_constructs() -> None:
    # axiom enforcement is panproto-side and not yet wired; we simply
    # confirm construction succeeds and the value round-trips.
    w = WithAxioms(age=42)
    assert w.age == 42


# -- inheritance -----------------------------------------------------------


class _Base(dx.Model):
    id: str


class _Derived(_Base):
    name: str = ""


def test_inherited_fields_present() -> None:
    specs = _Derived.__field_specs__
    assert set(specs) == {"id", "name"}


def test_derived_construct() -> None:
    d = _Derived(id="x")
    assert d.id == "x"
    assert d.name == ""
