"""Tests for the from_pydantic adapter."""

from typing import Annotated

import pytest
from annotated_types import Ge, Le, MinLen
from pydantic import BaseModel, Field

import didactic.api as dx
from didactic.pydantic import from_pydantic

# -- shape ---------------------------------------------------------------


class PydUser(BaseModel):
    """Simple Pydantic user with mixed defaults."""

    id: str
    email: str = Field(description="primary contact")
    display_name: str = ""


def test_returns_dx_model_subclass() -> None:
    User = from_pydantic(PydUser)
    assert issubclass(User, dx.Model)
    assert User.__name__ == "PydUser"


def test_field_specs_match_pydantic() -> None:
    User = from_pydantic(PydUser)
    assert set(User.__field_specs__) == {"id", "email", "display_name"}


def test_construction_works() -> None:
    User = from_pydantic(PydUser)
    u = User(id="u1", email="a@b.c")
    assert u.id == "u1"
    assert u.email == "a@b.c"
    assert u.display_name == ""


def test_required_inferred_from_pydantic() -> None:
    User = from_pydantic(PydUser)
    # `id` and `email` are both required (no default supplied to Field)
    assert User.__field_specs__["id"].is_required
    assert User.__field_specs__["email"].is_required
    # `display_name` has a default
    assert not User.__field_specs__["display_name"].is_required


def test_description_carried_over() -> None:
    User = from_pydantic(PydUser)
    assert User.__field_specs__["email"].description == "primary contact"


def test_custom_name() -> None:
    Renamed = from_pydantic(PydUser, name="Account")
    assert Renamed.__name__ == "Account"


# -- defaults & factories ------------------------------------------------


class PydWithFactory(BaseModel):
    tags: tuple[str, ...] = Field(default_factory=tuple)
    n: int = 0


def test_default_factory_carried_over() -> None:
    M = from_pydantic(PydWithFactory)
    spec = M.__field_specs__["tags"]
    assert spec.default_factory is tuple
    instance = M()
    assert instance.tags == ()
    assert instance.n == 0


# -- annotated metadata --------------------------------------------------


class PydWithConstraints(BaseModel):
    age: Annotated[int, Ge(0), Le(127)]
    nickname: Annotated[str, MinLen(1)]


def test_annotated_metadata_flows_through_to_axioms() -> None:
    M = from_pydantic(PydWithConstraints)
    spec = M.__field_specs__["age"]
    # axioms induced by Ge / Le show up on the dx side
    assert any("x >= 0" in a for a in spec.axioms)
    assert any("x <= 127" in a for a in spec.axioms)


def test_construction_with_annotated() -> None:
    M = from_pydantic(PydWithConstraints)
    m = M(age=25, nickname="alice")
    assert m.age == 25


# -- error paths ---------------------------------------------------------


def test_rejects_non_pydantic() -> None:
    with pytest.raises(TypeError, match="BaseModel"):
        from_pydantic(dict)  # type: ignore[arg-type]


def test_rejects_plain_class() -> None:
    class NotAPydanticModel:
        x: int

    with pytest.raises(TypeError, match="BaseModel"):
        from_pydantic(NotAPydanticModel)  # type: ignore[arg-type]


# -- alias support -------------------------------------------------------


class PydAliased(BaseModel):
    user_id: str = Field(alias="userId")


def test_alias_carried_over() -> None:
    M = from_pydantic(PydAliased)
    assert M.__field_specs__["user_id"].alias == "userId"


# -- examples / deprecated / json_schema_extra round-trip --------------


class PydMetadataRich(BaseModel):
    """Carries every pydantic-side metadata field we translate."""

    id: str = Field(examples=["u1", "u2"])
    legacy: str | None = Field(default=None, deprecated=True)
    public: str = Field(default="x", json_schema_extra={"x-public": True})


def test_examples_round_trip() -> None:
    M = from_pydantic(PydMetadataRich)
    assert tuple(M.__field_specs__["id"].examples) == ("u1", "u2")


def test_deprecated_round_trip() -> None:
    M = from_pydantic(PydMetadataRich)
    assert M.__field_specs__["legacy"].deprecated is True


def test_json_schema_extra_round_trip() -> None:
    M = from_pydantic(PydMetadataRich)
    extras = M.__field_specs__["public"].extras
    assert extras is not None
    assert extras.get("json_schema_extra") == {"x-public": True}


# -- required-detection helper ----------------------------------------


def test_field_with_default_is_not_required() -> None:
    """A pydantic field with a default is mapped to a non-required dx field."""

    class HasDefault(BaseModel):
        x: int = 0

    M = from_pydantic(HasDefault)
    assert not M.__field_specs__["x"].is_required


def test_field_with_factory_is_not_required() -> None:
    """A default_factory field maps to a non-required dx field."""

    class HasFactory(BaseModel):
        tags: tuple[str, ...] = Field(default_factory=tuple)

    M = from_pydantic(HasFactory)
    assert not M.__field_specs__["tags"].is_required


def test_internal_is_required_helper_classifies_pydantic_fields() -> None:
    """The internal ``_is_required`` helper agrees with Pydantic's own view."""
    from pydantic_core import PydanticUndefined

    from didactic.pydantic._adapter import _is_required

    class _M(BaseModel):
        required: str
        defaulted: str = "x"
        factoryed: tuple[str, ...] = Field(default_factory=tuple)

    assert _is_required(_M.model_fields["required"], PydanticUndefined) is True
    assert _is_required(_M.model_fields["defaulted"], PydanticUndefined) is False
    assert _is_required(_M.model_fields["factoryed"], PydanticUndefined) is False
