"""Tests for ``dx.Embed[T]`` sub-vertex composition."""

# Tests subscript ``model_dump()`` results (recursive ``FieldValue``
# union) and pass intentional wrong-type arguments to verify
# validation error paths. The chained-subscript narrowing and the
# negative-test argument types are noise; the runtime behaviour is
# what's under test. Tracked in panproto/didactic#1 for a structural
# fix (TypedDict for ``model_dump`` shape, Protocol for the negative
# test path).
# pyright: reportArgumentType=false, reportCallIssue=false, reportIndexIssue=false, reportOptionalSubscript=false, reportUnhashable=false

import pickle

import pytest

import didactic.api as dx
from didactic.theory._theory import build_theory_spec


class Address(dx.Model):
    """Embedded sub-model."""

    line1: str
    city: str = ""
    postal_code: str = ""


class Person(dx.Model):
    """Owns an embedded Address."""

    id: str
    name: str
    home: dx.Embed[Address]


# -- declaration ----------------------------------------------------------


def test_embed_field_has_embed_kind() -> None:
    spec = Person.__field_specs__["home"]
    assert spec.translation.inner_kind == "embed"
    assert spec.translation.sort == "Embed Address"


# -- construction --------------------------------------------------------


def test_construct_with_embedded_instance() -> None:
    addr = Address(line1="1 Main St", city="Townsville", postal_code="12345")
    p = Person(id="p1", name="Alice", home=addr)
    assert p.home == addr
    assert p.home.line1 == "1 Main St"
    assert p.home.city == "Townsville"


def test_embed_rejects_non_target_class() -> None:
    with pytest.raises(dx.ValidationError) as exc:
        Person(id="p1", name="Alice", home="not an Address")
    assert any(e.type == "type_error" for e in exc.value.entries)


def test_embed_rejects_wrong_model_type() -> None:
    class Other(dx.Model):
        x: str

    with pytest.raises(dx.ValidationError):
        Person(id="p1", name="Alice", home=Other(x="hi"))


# -- with_ ---------------------------------------------------------------


def test_with_replaces_embedded() -> None:
    p = Person(id="p1", name="Alice", home=Address(line1="1 Main"))
    new_addr = Address(line1="2 Other St", city="Elsewhere")
    p2 = p.with_(home=new_addr)
    assert p2.home.line1 == "2 Other St"
    assert p2.home.city == "Elsewhere"
    # original unchanged
    assert p.home.line1 == "1 Main"


# -- serialisation -------------------------------------------------------


def test_dict_round_trip() -> None:
    p = Person(id="p1", name="Alice", home=Address(line1="1 Main", city="Town"))
    payload = p.model_dump()
    # the embedded model's fields appear nested under the field name
    assert payload["home"]["line1"] == "1 Main"
    assert payload["home"]["city"] == "Town"
    # round-trip
    p2 = Person.model_validate(payload)
    assert p == p2


def test_json_round_trip() -> None:
    p = Person(id="p1", name="Alice", home=Address(line1="1 Main", city="Town"))
    raw = p.model_dump_json()
    p2 = Person.model_validate_json(raw)
    assert p == p2
    assert p2.home.line1 == "1 Main"


def test_pickle_round_trip() -> None:
    p = Person(id="p1", name="Alice", home=Address(line1="1 Main"))
    blob = pickle.dumps(p)
    p2 = pickle.loads(blob)
    assert p == p2


# -- equality / hashing --------------------------------------------------


def test_two_persons_with_same_embedded_address_are_equal() -> None:
    p1 = Person(id="p1", name="Alice", home=Address(line1="1 Main"))
    p2 = Person(id="p1", name="Alice", home=Address(line1="1 Main"))
    assert p1 == p2
    assert hash(p1) == hash(p2)


def test_different_embedded_addresses_inequal() -> None:
    p1 = Person(id="p1", name="Alice", home=Address(line1="1 Main"))
    p2 = Person(id="p1", name="Alice", home=Address(line1="2 Other"))
    assert p1 != p2


# -- theory spec --------------------------------------------------------


def test_theory_spec_emits_embed_as_edge_to_target_sort() -> None:
    spec = build_theory_spec(Person)
    op_by_name = {op["name"]: op for op in spec["ops"]}
    # the embed op outputs the target's primary sort. Containment is
    # didactic-private metadata until we round-trip the panproto-side
    # canonical key.
    assert op_by_name["home"]["output"] == "Address"


def test_theory_spec_no_constraint_sort_for_embed() -> None:
    spec = build_theory_spec(Person)
    sort_names = {s["name"] for s in spec["sorts"]}
    # Embed fields don't get their own constraint sort
    assert "Person_home" not in sort_names


# -- nested embed ------------------------------------------------------


class _Inner(dx.Model):
    n: int


class _Middle(dx.Model):
    inner: dx.Embed[_Inner]


class _Outer(dx.Model):
    middle: dx.Embed[_Middle]


def test_nested_embed_round_trip() -> None:
    o = _Outer(middle=_Middle(inner=_Inner(n=42)))
    assert o.middle.inner.n == 42
    o2 = _Outer.model_validate(o.model_dump())
    assert o == o2
    assert o2.middle.inner.n == 42


def test_nested_embed_json_round_trip() -> None:
    o = _Outer(middle=_Middle(inner=_Inner(n=7)))
    raw = o.model_dump_json()
    o2 = _Outer.model_validate_json(raw)
    assert o == o2
