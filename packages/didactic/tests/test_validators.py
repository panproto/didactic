"""Tests for the ``@dx.validates`` decorator end-to-end.

Covers the metaclass collection of ``@validates``-tagged methods, the
runtime invocation pipeline (before / after, value mutation,
ValidationError shape), inheritance and override semantics, and the
three method shapes (instance, classmethod, staticmethod).
"""

from __future__ import annotations

import pytest

import didactic.api as dx


# -- after-mode validators -------------------------------------------------


class _NameModel(dx.Model):
    name: str

    @dx.validates("name")
    def _check_name(self, value: str) -> str:
        if not value.strip():
            msg = "name cannot be empty"
            raise ValueError(msg)
        return value.strip()


def test_after_validator_runs_and_replaces_value() -> None:
    """An ``after`` validator's return value replaces the stored value."""
    m = _NameModel(name="  alice  ")
    assert m.name == "alice"


def test_after_validator_raises_validation_error() -> None:
    """A validator's ``raise ValueError`` surfaces as ``ValidationError``."""
    with pytest.raises(dx.ValidationError) as exc:
        _NameModel(name="")
    entries = exc.value.entries
    assert len(entries) == 1
    assert entries[0].loc == ("name",)
    assert entries[0].type == "validator_error"
    assert "empty" in entries[0].msg


def test_after_validator_runs_on_with_too() -> None:
    """``with_(...)`` runs the same validator pipeline."""
    m = _NameModel(name="alice")
    with pytest.raises(dx.ValidationError):
        m.with_(name="")


# -- before-mode validators ------------------------------------------------


class _NormalisedEmail(dx.Model):
    email: str

    @dx.validates("email", mode="before")
    def _normalise(self, value: str) -> str:
        return value.lower()


def test_before_validator_runs_before_encoding() -> None:
    """A ``before`` validator's output is what gets type-validated and stored."""
    m = _NormalisedEmail(email="ALICE@EXAMPLE.COM")
    assert m.email == "alice@example.com"


# -- @classmethod form (matches the decorator's docstring example) ---------


class _LowerEmail(dx.Model):
    email: str

    @dx.validates("email")
    @classmethod
    def _email_lower(cls, value: str) -> str:
        # the cls argument actually receives the class
        assert cls is _LowerEmail
        return value.lower()


def test_classmethod_validator_form() -> None:
    m = _LowerEmail(email="BOB@EXAMPLE.COM")
    assert m.email == "bob@example.com"


# -- @staticmethod form ----------------------------------------------------


class _TrimEmail(dx.Model):
    email: str

    @dx.validates("email")
    @staticmethod
    def _trim(value: str) -> str:
        return value.strip()


def test_staticmethod_validator_form() -> None:
    m = _TrimEmail(email="  c@d.e  ")
    assert m.email == "c@d.e"


# -- multiple fields share a single validator ------------------------------


class _Pair(dx.Model):
    first: str
    last: str

    @dx.validates("first", "last")
    def _trim(self, value: str) -> str:
        return value.strip()


def test_one_validator_for_multiple_fields() -> None:
    m = _Pair(first="  a  ", last="  b  ")
    assert (m.first, m.last) == ("a", "b")


# -- inheritance -----------------------------------------------------------


class _BaseV(dx.Model):
    name: str

    @dx.validates("name")
    def _strip(self, value: str) -> str:
        return value.strip()


class _ChildV(_BaseV):
    pass


def test_subclass_inherits_validator() -> None:
    m = _ChildV(name="  z  ")
    assert m.name == "z"


class _ChildOverride(_BaseV):
    @dx.validates("name")
    def _strip(self, value: str) -> str:
        return value.strip().upper()


def test_subclass_can_override_validator_with_new_marker() -> None:
    m = _ChildOverride(name="  z  ")
    assert m.name == "Z"


class _ChildSilentlyShadow(_BaseV):
    # subclass shadows the validator method WITHOUT re-applying @validates;
    # the subclass intent is "stop validating", and the runtime honours it.
    def _strip(self, value: str) -> str:  # type: ignore[override]
        return value


def test_subclass_method_without_marker_unregisters_validator() -> None:
    m = _ChildSilentlyShadow(name="  z  ")
    assert m.name == "  z  "


# -- composition with converter and Annotated constraints -----------------


class _WithConverter(dx.Model):
    code: str = dx.field(converter=lambda v: str(v).upper())

    @dx.validates("code")
    def _check(self, value: str) -> str:
        # converter runs first, so we always see uppercase here
        if not value.isupper():
            msg = "must be upper after converter"
            raise ValueError(msg)
        return value


def test_validator_runs_after_converter() -> None:
    m = _WithConverter(code="abc")
    assert m.code == "ABC"


# -- multiple validators on one field run in registration order ------------


class _Chain(dx.Model):
    word: str

    @dx.validates("word")
    def _strip(self, value: str) -> str:
        return value.strip()

    @dx.validates("word")
    def _upper(self, value: str) -> str:
        return value.upper()


def test_multiple_validators_chain_in_order() -> None:
    m = _Chain(word="  hi  ")
    assert m.word == "HI"
