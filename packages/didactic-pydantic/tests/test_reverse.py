"""Tests for to_pydantic (didactic Model -> Pydantic BaseModel)."""

# Tests instantiate dynamically-created Pydantic ``BaseModel``
# subclasses from ``to_pydantic`` and access their fields. Pyright
# can't follow the dynamic ``create_model`` round-trip, so attribute
# access on the returned instance comes back as Unknown. Tracked in
# panproto/didactic#1.

from __future__ import annotations

import pytest
from pydantic import BaseModel

import didactic.api as dx
from didactic.pydantic import from_pydantic, to_pydantic

# -- basic translation -------------------------------------------------


def test_to_pydantic_returns_basemodel_subclass() -> None:
    class User(dx.Model):
        id: str
        email: str

    PydUser = to_pydantic(User)
    assert isinstance(PydUser, type)
    assert issubclass(PydUser, BaseModel)
    assert PydUser.__name__ == "User"


def test_to_pydantic_preserves_module() -> None:
    class User(dx.Model):
        id: str

    PydUser = to_pydantic(User)
    assert PydUser.__module__ == User.__module__


def test_to_pydantic_custom_name() -> None:
    class User(dx.Model):
        id: str

    PydUser = to_pydantic(User, name="ExternalUser")
    assert PydUser.__name__ == "ExternalUser"


def test_to_pydantic_rejects_non_model() -> None:
    class NotAModel:
        pass

    with pytest.raises(TypeError, match="didactic.Model subclass"):
        to_pydantic(NotAModel)  # type: ignore[arg-type]


# -- field metadata ----------------------------------------------------


def test_required_field_has_no_default() -> None:
    class User(dx.Model):
        id: str

    PydUser = to_pydantic(User)
    info = PydUser.model_fields["id"]
    assert info.is_required()


def test_default_value_carries_through() -> None:
    class User(dx.Model):
        id: str
        email: str = "unknown"

    PydUser = to_pydantic(User)
    info = PydUser.model_fields["email"]
    assert info.default == "unknown"


def test_default_factory_carries_through() -> None:
    class User(dx.Model):
        id: str
        tags: tuple[str, ...] = dx.field(default_factory=tuple)

    PydUser = to_pydantic(User)
    info = PydUser.model_fields["tags"]
    assert info.default_factory is tuple


def test_description_carries_through() -> None:
    class User(dx.Model):
        id: str
        email: str = dx.field(description="primary contact")

    PydUser = to_pydantic(User)
    assert PydUser.model_fields["email"].description == "primary contact"


def test_examples_carry_through() -> None:
    class User(dx.Model):
        id: str = dx.field(examples=("u1", "u2"))

    PydUser = to_pydantic(User)
    examples = PydUser.model_fields["id"].examples
    assert examples is not None
    assert list(examples) == ["u1", "u2"]


def test_alias_carries_through() -> None:
    class User(dx.Model):
        id: str = dx.field(alias="userId")

    PydUser = to_pydantic(User)
    assert PydUser.model_fields["id"].alias == "userId"


def test_deprecated_carries_through() -> None:
    class User(dx.Model):
        id: str
        legacy_id: str | None = dx.field(default=None, deprecated=True)

    PydUser = to_pydantic(User)
    assert PydUser.model_fields["legacy_id"].deprecated


# -- instantiation -----------------------------------------------------


def test_instantiate_pydantic_model() -> None:
    class User(dx.Model):
        id: str
        email: str

    PydUser = to_pydantic(User)
    u = PydUser(id="u1", email="a@b.c")
    dumped = u.model_dump()
    assert dumped["id"] == "u1"
    assert dumped["email"] == "a@b.c"


def test_pydantic_model_validates_inputs() -> None:
    class User(dx.Model):
        id: str
        age: int

    PydUser = to_pydantic(User)
    u = PydUser(id="u1", age="42")  # pydantic coerces str->int
    assert u.model_dump()["age"] == 42


# -- round-trip --------------------------------------------------------


def test_round_trip_dx_to_pydantic_to_dx() -> None:
    """A didactic Model -> Pydantic -> didactic round trip preserves shape.

    Field annotations and metadata that both adapters can carry should
    survive a full round trip.
    """

    class User(dx.Model):
        id: str
        email: str = dx.field(description="primary contact")
        nickname: str = ""

    PydUser = to_pydantic(User)
    UserBack = from_pydantic(PydUser)

    assert set(UserBack.__field_specs__.keys()) == {"id", "email", "nickname"}
    assert UserBack.__field_specs__["email"].description == "primary contact"
    assert UserBack.__field_specs__["nickname"].default == ""


def test_round_trip_pydantic_to_dx_to_pydantic() -> None:
    """A Pydantic -> didactic -> Pydantic round trip preserves shape."""
    from pydantic import Field

    class PydUser(BaseModel):
        id: str
        email: str = Field(description="primary contact")

    DxUser = from_pydantic(PydUser)
    PydUserBack = to_pydantic(DxUser)

    assert set(PydUserBack.model_fields.keys()) == {"id", "email"}
    assert PydUserBack.model_fields["email"].description == "primary contact"


# -- skipped fields ----------------------------------------------------


def test_computed_fields_are_skipped() -> None:
    """``@dx.computed`` properties don't appear in the Pydantic shape."""

    class User(dx.Model):
        first: str
        last: str

        @dx.computed
        def full_name(self) -> str:
            return f"{self.first} {self.last}"

    PydUser = to_pydantic(User)
    assert "full_name" not in PydUser.model_fields
    assert set(PydUser.model_fields.keys()) == {"first", "last"}
