"""Tests for ``dx.Ref[T]`` cross-vertex references."""

# Protocols in a v0.1.x patch.

from typing import cast, get_args, get_origin

import pytest

import didactic.api as dx
from didactic.fields._refs import (
    BackrefMarker,
    EmbedSentinel,
    RefSentinel,
    find_ref_marker,
)
from didactic.theory._theory import build_theory_spec
from didactic.types._types import classify, expand_type_alias, unwrap_annotated

# -- Ref subscript shape ---------------------------------------------------


class User(dx.Model):
    """Target model used as the Ref destination."""

    id: str


class Order(dx.Model):
    """Cross-references a User."""

    id: str
    user: dx.Ref[User]


def test_ref_subscript_produces_annotated_str() -> None:
    ann = dx.Ref[User]
    # `Ref[T]` is a PEP 695 type alias whose value is
    # ``Annotated[str, REF_MARKER, T]``; expanding the alias yields the
    # underlying Annotated form.
    base, meta = unwrap_annotated(ann)
    assert base is str
    assert any(isinstance(m, RefSentinel) for m in meta)


def test_ref_marker_extraction() -> None:
    ann = dx.Ref[User]
    _, meta = unwrap_annotated(ann)
    marker = find_ref_marker(meta)
    assert marker is not None
    assert marker.target is User


def test_ref_with_forward_string() -> None:
    # forward references via string (declared before the target exists)
    ann = dx.Ref["UserNotYet"]
    _, meta = unwrap_annotated(ann)
    marker = find_ref_marker(meta)
    assert marker is not None
    assert marker.target == "UserNotYet"


# -- classification -------------------------------------------------------


def test_ref_translation_sort() -> None:
    t = classify(dx.Ref[User])
    assert t.sort == "Ref User"
    assert t.inner_kind == "ref"


def test_ref_encode_string_id() -> None:
    t = classify(dx.Ref[User])
    assert t.encode("u1") == "u1"


def test_ref_encode_model_instance() -> None:
    u = User(id="u1")
    t = classify(dx.Ref[User])
    assert t.encode(u) == "u1"


def test_ref_encode_rejects_unrelated_value() -> None:
    t = classify(dx.Ref[User])
    with pytest.raises(TypeError, match="Ref"):
        t.encode(42)


# -- model with a Ref field ----------------------------------------------


def test_order_has_user_field() -> None:
    specs = Order.__field_specs__
    assert "user" in specs
    assert specs["user"].translation.inner_kind == "ref"


def test_order_construct_with_string_id() -> None:
    o = Order(id="o1", user="u1")
    assert o.user == "u1"


def test_order_construct_with_user_instance() -> None:
    u = User(id="u1")
    o = Order.model_validate({"id": "o1", "user": u})
    assert o.user == "u1"


def test_order_with_replaces_user() -> None:
    o = Order(id="o1", user="u1")
    o2 = o.with_(user="u2")
    assert o2.user == "u2"


def test_order_dump_round_trip() -> None:
    o = Order(id="o1", user="u1")
    assert Order.model_validate(o.model_dump()) == o


def test_order_json_round_trip() -> None:
    o = Order(id="o1", user="u1")
    assert Order.model_validate_json(o.model_dump_json()) == o


# -- theory spec ----------------------------------------------------------


def test_theory_spec_emits_ref_as_edge() -> None:
    spec = build_theory_spec(Order)
    # Ref fields produce an edge op directly to the target sort, not a
    # constraint-sort + accessor pair
    sort_names = {cast("str", s["name"]) for s in spec["sorts"]}
    assert "Order_user" not in sort_names  # no constraint sort for the Ref
    op_by_name = {op["name"]: op for op in spec["ops"]}
    # the output is a panproto SortExpr in untagged form: a bare string
    # for a no-args sort name.
    assert op_by_name["user"]["output"] == "User"


def test_theory_spec_keeps_scalar_fields_as_constraints() -> None:
    spec = build_theory_spec(Order)
    sort_names = {cast("str", s["name"]) for s in spec["sorts"]}
    # the `id: str` field should still get a constraint sort
    assert "Order_id" in sort_names


# -- markers exist (Embed / Backref reserved) ----------------------------


def test_embed_marker_exposed() -> None:
    ann = dx.Embed[User]
    base, meta = unwrap_annotated(ann)
    assert base is User
    assert any(isinstance(m, EmbedSentinel) for m in meta)


def test_backref_marker_requires_two_params() -> None:
    with pytest.raises(TypeError, match="two parameters"):
        dx.Backref[User]


def test_backref_marker_two_params() -> None:
    ann = dx.Backref[User, "user"]
    meta = get_args(ann)[1:]
    marker = next(m for m in meta if isinstance(m, BackrefMarker))
    assert marker.target is User
    assert marker.inverse_field == "user"


# -- pyright-shape: ann appears as Annotated under the hood ------------


def test_ref_origin_is_annotated() -> None:
    ann = dx.Ref[User]
    # The PEP 695 alias presents itself as a generic-alias of the alias
    # itself; ``get_origin`` returns the ``TypeAliasType``. After expanding
    # the alias, the underlying form is ``Annotated[str, ...]`` and the
    # base type is ``str``.
    assert get_origin(ann) is not None
    expanded = expand_type_alias(ann)
    base, _ = unwrap_annotated(expanded)
    assert base is str
