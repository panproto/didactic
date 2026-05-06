"""``Model.with_()`` accepts concrete ``dict[str, X]`` shapes without casts.

Pins the v0.6.2 type-shape change: ``FieldValue``'s recursive mapping
arm uses ``Mapping`` (covariant in its value type) instead of the
invariant ``dict``. Without this, every call site that passes a
typed ``dict[str, MyValue]`` to ``with_()`` had to cast through the
``FieldValue`` union; with it, the natural form type-checks.

These tests run at runtime; the type-checker contract is pinned by
the issue-#36 PR description and the module-level pyright sweep that
runs in CI.
"""

from __future__ import annotations

import didactic.api as dx


type _MyValue = str | int | None | dict[str, "_MyValue"] | tuple["_MyValue", ...]


class _Holder(dx.Model):
    metadata: dict[str, _MyValue] = dx.field(default_factory=dict)
    tagged_elements: dict[str, tuple[str, ...]] = dx.field(default_factory=dict)


def test_with_accepts_typed_dict_str_to_my_value() -> None:
    """The issue's exact shape: ``dict[str, _MyValue]`` flows into ``with_()``."""
    h = _Holder()
    md: dict[str, _MyValue] = {"k": "v", "nested": {"inner": 42}}
    new = h.with_(metadata=md)
    assert new.metadata == md


def test_with_accepts_typed_dict_str_to_tuple_of_str() -> None:
    """``dict[str, tuple[str, ...]]`` is a structural subset of FieldValue."""
    h = _Holder()
    payload: dict[str, tuple[str, ...]] = {"row1": ("a", "b"), "row2": ("c",)}
    new = h.with_(tagged_elements=payload)
    assert new.tagged_elements == payload


def test_with_accepts_inline_dict_literal() -> None:
    """The natural ``with_(metadata={...})`` literal form keeps working."""
    h = _Holder()
    new = h.with_(metadata={"k": "v"})
    assert new.metadata == {"k": "v"}


def test_with_round_trips_through_model_dump() -> None:
    """The looser type-checker contract preserves runtime semantics."""
    h = _Holder()
    new = h.with_(metadata={"a": 1, "b": "two", "c": None})
    payload = new.model_dump_json()
    out = _Holder.model_validate_json(payload)
    assert out.metadata == {"a": 1, "b": "two", "c": None}
