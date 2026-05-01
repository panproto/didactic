"""Tests for the ``@dx.computed`` decorator."""

import json

import didactic.api as dx


class Person(dx.Model):
    """Model with two computed fields."""

    first_name: str
    last_name: str

    @dx.computed
    def full_name(self) -> str:
        """Concatenate the two parts."""
        return f"{self.first_name} {self.last_name}"

    @dx.computed
    def initials(self) -> str:
        """Two-letter initials."""
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()


class Order(dx.Model):
    """Model with a computed call requiring options."""

    qty: int
    unit_price: int

    @dx.computed(materialise=False)
    def total(self) -> int:
        """Quantity times price."""
        return self.qty * self.unit_price


# -- registration --------------------------------------------------------


def test_computed_fields_collected() -> None:
    assert set(Person.__computed_fields__) == {"full_name", "initials"}
    assert Order.__computed_fields__ == ("total",)


def test_no_computed_fields_on_simple_model() -> None:
    class Bare(dx.Model):
        x: int

    assert Bare.__computed_fields__ == ()


# -- access --------------------------------------------------------------


def test_computed_evaluated_on_access() -> None:
    p = Person(first_name="Ada", last_name="Lovelace")
    assert p.full_name == "Ada Lovelace"
    assert p.initials == "AL"


def test_with_keyword_arg_form() -> None:
    o = Order(qty=3, unit_price=12)
    assert o.total == 36


def test_computed_recomputed_after_with_() -> None:
    p = Person(first_name="Ada", last_name="Lovelace")
    p2 = p.with_(last_name="Byron")
    assert p2.full_name == "Ada Byron"
    assert p2.initials == "AB"


# -- model_dump includes computed fields --------------------------------


def test_model_dump_includes_computed() -> None:
    p = Person(first_name="Ada", last_name="Lovelace")
    payload = p.model_dump()
    assert payload["full_name"] == "Ada Lovelace"
    assert payload["initials"] == "AL"
    # stored fields still appear too
    assert payload["first_name"] == "Ada"
    assert payload["last_name"] == "Lovelace"


def test_model_dump_round_trip_tolerates_computed_in_payload() -> None:
    p = Person(first_name="Ada", last_name="Lovelace")
    p2 = Person.model_validate(p.model_dump())
    assert p == p2


def test_json_round_trip_includes_computed() -> None:
    p = Person(first_name="Ada", last_name="Lovelace")
    parsed = json.loads(p.model_dump_json())
    assert parsed["full_name"] == "Ada Lovelace"
    assert parsed["initials"] == "AL"
    p2 = Person.model_validate_json(p.model_dump_json())
    assert p == p2


# -- inheritance --------------------------------------------------------


class Greeter(dx.Model):
    """Base with one computed field."""

    name: str

    @dx.computed
    def greeting(self) -> str:
        return f"Hello, {self.name}"


class FormalGreeter(Greeter):
    """Adds a second computed field."""

    title: str = ""

    @dx.computed
    def formal_greeting(self) -> str:
        prefix = f"{self.title} " if self.title else ""
        return f"Hello, {prefix}{self.name}"


def test_inherited_computed_fields() -> None:
    assert "greeting" in FormalGreeter.__computed_fields__
    assert "formal_greeting" in FormalGreeter.__computed_fields__


def test_inherited_computed_evaluation() -> None:
    g = FormalGreeter(name="Ada", title="Dr.")
    assert g.greeting == "Hello, Ada"
    assert g.formal_greeting == "Hello, Dr. Ada"
