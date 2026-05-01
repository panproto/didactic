"""JSON / pickle serde tests for Model.

Notes
-----
These tests do *not* use ``from __future__ import annotations`` so the
modern PEP 649 annotation path is exercised end-to-end.
"""

import json
import pickle
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

import didactic.api as dx


class Mixed(dx.Model):
    """Test model with a representative mix of field types."""

    id: str
    age: int
    score: float
    active: bool = True
    salary: Decimal = Decimal("0.00")
    when: datetime = datetime(2026, 1, 1, 0, 0, 0)
    birthday: date | None = None
    uid: UUID = UUID("12345678-1234-5678-1234-567812345678")
    tags: tuple[str, ...] = ()
    nicknames: frozenset[str] = frozenset()


def _example() -> Mixed:
    return Mixed(
        id="m1",
        age=33,
        score=1.5,
        active=False,
        salary=Decimal("1234.56"),
        when=datetime(2026, 4, 30, 12, 0, 0),
        birthday=date(1992, 6, 15),
        uid=UUID("87654321-4321-8765-4321-876587658765"),
        tags=("a", "b", "c"),
        nicknames=frozenset({"x", "y"}),
    )


# -- model_dump / model_validate -------------------------------------------


def test_dict_round_trip() -> None:
    m = _example()
    dumped = m.model_dump()
    m2 = Mixed.model_validate(dumped)
    assert m == m2


# -- model_dump_json / model_validate_json ----------------------------------


def test_json_round_trip() -> None:
    m = _example()
    raw = m.model_dump_json()
    parsed = json.loads(raw)
    # the JSON dict has the right shape
    assert parsed["id"] == "m1"
    assert parsed["age"] == 33
    assert parsed["active"] is False
    assert parsed["salary"] == "1234.56"
    assert parsed["when"] == "2026-04-30T12:00:00"
    assert parsed["birthday"] == "1992-06-15"
    assert parsed["tags"] == ["a", "b", "c"]
    assert sorted(parsed["nicknames"]) == ["x", "y"]
    # round-trip recovers the original
    m2 = Mixed.model_validate_json(raw)
    assert m == m2


def test_json_indent_pretty() -> None:
    m = _example()
    pretty = m.model_dump_json(indent=2)
    assert "\n" in pretty
    # indented output is still valid and round-trips
    m2 = Mixed.model_validate_json(pretty)
    assert m == m2


def test_json_validate_bytes() -> None:
    m = _example()
    raw = m.model_dump_json().encode("utf-8")
    m2 = Mixed.model_validate_json(raw)
    assert m == m2


def test_json_validate_rejects_array() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        Mixed.model_validate_json("[1, 2, 3]")
    assert any(e.type == "type_error" for e in exc.value.entries)


def test_json_validate_rejects_unknown_field() -> None:
    payload = {"id": "x", "age": 1, "score": 0.0, "bogus": 99}
    with pytest.raises(dx.ValidationError):
        Mixed.model_validate_json(json.dumps(payload))


# -- pickle ---------------------------------------------------------------


def test_pickle_round_trip() -> None:
    m = _example()
    blob = pickle.dumps(m)
    m2 = pickle.loads(blob)
    assert m == m2
    assert hash(m) == hash(m2)


# -- minimal-shape model --------------------------------------------------


class Tiny(dx.Model):
    """A single-field model — shortest path through the serde pipeline."""

    name: str


def test_tiny_json_round_trip() -> None:
    t = Tiny(name="hello")
    assert Tiny.model_validate_json(t.model_dump_json()) == t


def test_tiny_pickle_round_trip() -> None:
    t = Tiny(name="hello")
    assert pickle.loads(pickle.dumps(t)) == t
