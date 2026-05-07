"""``dx.field(opaque=True)`` stores by-reference, skips classification.

A field declared with ``opaque=True`` accepts any Python value
without going through the type-translation pipeline. The value
lives on the per-instance ``_opaque_storage`` side table; attribute
access returns it identity-equal; ``with_()`` updates it without
re-classification; ``model_dump_json`` writes ``null`` for the
field (opaque values don't have a wire form by contract).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import pytest

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue


class _Functor(Protocol):
    """A typeclass-shaped ABC the runtime carries by reference."""

    def fmap(self, f: object, /) -> object: ...


class _IdFunctor:
    def fmap(self, f: object, /) -> object:
        return f


class _Handler(dx.Model):
    target: _Functor = dx.field(opaque=True)
    name: str = "anon"


def test_opaque_field_accepts_any_python_object() -> None:
    f = _IdFunctor()
    h = _Handler(target=f, name="h1")
    assert h.target is f
    assert h.name == "h1"


def test_opaque_field_preserves_identity_through_with_() -> None:
    f1 = _IdFunctor()
    f2 = _IdFunctor()
    h = _Handler(target=f1)
    h2 = h.with_(target=cast("FieldValue", f2))
    assert h.target is f1
    assert h2.target is f2
    assert h is not h2


def test_opaque_field_writes_null_to_json() -> None:
    """JSON output writes ``null`` for opaque fields by contract.

    Opaque values don't have a wire form; ``model_dump_json`` writes
    ``null`` so the surrounding payload is still valid JSON. Callers
    that want a real serialisation path use a regular field type.
    """
    h = _Handler(target=_IdFunctor(), name="h1")
    payload = h.model_dump_json()
    assert '"target": null' in payload
    assert '"name": "h1"' in payload


class _HandlerWithDefault(dx.Model):
    target: object = dx.field(default=None, opaque=True)
    name: str = "anon"


def test_opaque_field_validate_json_falls_back_to_default() -> None:
    """``model_validate_json`` drops the ``null`` placeholder.

    Opaque fields don't reconstruct from the wire form; the placeholder
    is ignored and the field falls back to its declared default. The
    non-opaque sibling fields round-trip normally.
    """
    h = _HandlerWithDefault(target=_IdFunctor(), name="h1")
    rt = _HandlerWithDefault.model_validate_json(h.model_dump_json())
    assert rt.name == "h1"
    assert rt.target is None


def test_opaque_field_validate_json_required_without_default_errors() -> None:
    """A required opaque field surfaces as ``missing_required`` on round-trip."""
    h = _Handler(target=_IdFunctor(), name="h1")
    with pytest.raises(dx.ValidationError) as exc:
        _Handler.model_validate_json(h.model_dump_json())
    types = {e.type for e in exc.value.entries}
    assert "missing_required" in types


def test_opaque_field_default() -> None:
    """Defaults work for opaque fields."""

    class _M(dx.Model):
        cb: object = dx.field(default=None, opaque=True)

    m = _M()
    assert m.cb is None

    def callable_ref(x: object) -> object:
        return x

    m2 = _M(cb=callable_ref)
    assert m2.cb is callable_ref


def test_opaque_field_default_factory() -> None:
    sentinel: list[int] = []

    class _M(dx.Model):
        cb: list[int] = dx.field(default_factory=lambda: sentinel, opaque=True)

    m = _M()
    assert m.cb is sentinel


def test_opaque_field_with_unknown_kwarg_still_rejects() -> None:
    """The opaque path doesn't loosen the unknown-field check."""
    with pytest.raises(dx.ValidationError):
        _Handler(target=_IdFunctor(), bogus=1)  # type: ignore[call-arg]


def test_opaque_field_required_when_no_default() -> None:
    """An opaque field without a default is still required."""
    with pytest.raises(dx.ValidationError) as exc:
        _Handler()  # type: ignore[call-arg]
    types = {e.type for e in exc.value.entries}
    assert "missing_required" in types


def test_opaque_field_repr_renders_python_repr() -> None:
    f = _IdFunctor()
    h = _Handler(target=f)
    out = repr(h)
    assert "target=" in out
    assert "anon" in out
