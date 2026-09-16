"""``key=value`` overrides: key syntax and annotation-directed decoding.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

import enum
from typing import Annotated, Literal

import pytest
from annotated_types import Ge

import didactic.api as dx
from didactic.settings import (
    CoercionError,
    Origin,
    OverrideSyntaxError,
    Settings,
    compose,
    compose_traced,
    decode_text,
    parse_override,
)
from didactic.settings._scalars import validate_override_key

from ._schemas import LinearDecoder, RunSpec, subtree

# -- parse_override -----------------------------------------------------------


def test_parse_override_splits_on_the_first_equals_and_keeps_the_text() -> None:
    assert parse_override("a.b=x=y") == ("a.b", "x=y")
    assert parse_override(" a.b =  1 ") == ("a.b", "  1 ")
    assert parse_override("a=") == ("a", "")


def test_parse_override_missing_equals() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        parse_override("no_equals_here")
    assert str(info.value) == (
        "Override 'no_equals_here' is missing '='; expected key=value"
    )


def test_parse_override_empty_key() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        parse_override("=1")
    assert str(info.value) == "Override '=1' has an empty key; expected key=value"


def test_parse_override_empty_segment() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        parse_override("a..b=1")
    assert str(info.value) == "Override key 'a..b' has an empty segment"


def test_parse_override_list_index_is_refused() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        parse_override("tags.0=x")
    assert str(info.value) == (
        "Override key 'tags.0' indexes into a list; lists are set whole, as tags=[...]"
    )
    with pytest.raises(OverrideSyntaxError, match="indexes into a list"):
        validate_override_key("a.b.12.c")


def test_validate_override_key_empty() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        validate_override_key("")
    assert str(info.value) == "Override key is empty; expected a dotted path"


# -- decode_text --------------------------------------------------------------


class Colour(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


class Inner(dx.Model, extra="forbid"):
    x: int = 0


ORIGIN = Origin("override", name="k=v")


@pytest.mark.parametrize(
    ("text", "annotation", "expected"),
    [
        ("123", str, "123"),
        ("true", str, "true"),
        ("", str, ""),
        ("1", bool, True),
        ("0", bool, False),
        ("true", bool, True),
        ("FALSE", bool, False),
        ("yes", bool, True),
        ("No", bool, False),
        ("on", bool, True),
        ("off", bool, False),
        ("42", int, 42),
        (" -3 ", int, -3),
        ("1.5", float, 1.5),
        ("2", float, 2.0),
        ("1e-3", float, 0.001),
        ("null", int | None, None),
        ("", int | None, None),
        ("~", int | None, None),
        ("7", int | None, 7),
        ("5", Annotated[int, Ge(1)], 5),
        ("a", Literal["a", "b"], "a"),
        ("2", Literal[1, 2], 2),
        ("True", Literal[True, False], True),
        ("false", Literal[True, False], False),
        ("RED", Colour, "red"),
        ("blue", Colour, "blue"),
        ("HIGH", Level, 2),
        ("1", Level, 1),
        ("1,2,3", tuple[int, ...], [1, 2, 3]),
        ("[1,2,3]", tuple[int, ...], [1, 2, 3]),
        ("", tuple[int, ...], []),
        ("a, b", tuple[str, ...], ["a", "b"]),
        ('["a,b", "c"]', tuple[str, ...], ["a,b", "c"]),
        ("1,2", frozenset[int], [1, 2]),
        ("null", tuple[int, ...] | None, None),
        ('{"a": "1"}', dict[str, str], {"a": "1"}),
        ('{"x": 3}', Inner, {"x": 3}),
        ("3", int | str, 3),
        ("x", int | str, "x"),
    ],
)
def test_decode_text_matrix(text: str, annotation: object, expected: object) -> None:
    assert decode_text(text, annotation, path="k", origin=ORIGIN) == expected


@pytest.mark.parametrize(
    ("text", "annotation", "expected"),
    [
        ("maybe", bool, "bool"),
        ("x", int, "int"),
        ("1.5", int, "int"),
        ("x", float, "float"),
        ("c", Literal["a", "b"], "one of ['a', 'b']"),
        ("3", Literal[1, 2], "one of [1, 2]"),
        ("GREEN", Colour, "Colour"),
        ("x", int | None, "int"),
        ("1,x", tuple[int, ...], "int"),
        ("[1,", tuple[int, ...], None),
        ("a: 1", dict[str, str], "JSON object text for dict[str, str]"),
        ("x", Inner, "JSON object text for Inner"),
    ],
)
def test_decode_text_refusals(
    text: str, annotation: object, expected: str | None
) -> None:
    if expected is None:
        with pytest.raises(OverrideSyntaxError, match="is not valid JSON"):
            decode_text(text, annotation, path="k", origin=ORIGIN)
        return
    with pytest.raises(CoercionError) as info:
        decode_text(text, annotation, path="k", origin=ORIGIN)
    e = info.value
    assert e.path == "k"
    assert e.expected == expected
    assert e.text in (text, text.rpartition(",")[2])
    assert str(e).startswith(
        f"Config key 'k' expects {expected} (set by override:k=v); got "
    )


def test_decode_text_bool_refusal_names_path_expected_and_text() -> None:
    with pytest.raises(CoercionError) as info:
        compose(
            schema=RunSpec,
            overrides=[
                "model.combinator_decoders.fwd.kind=linear",
                "model.combinator_decoders.fwd.bias=maybe",
            ],
        )
    e = info.value
    assert e.path == "model.combinator_decoders.fwd.bias"
    assert e.expected == "bool"
    assert e.text == "maybe"
    assert str(e) == (
        "Config key 'model.combinator_decoders.fwd.bias' expects bool "
        "(set by override:model.combinator_decoders.fwd.bias=maybe); got 'maybe'"
    )


def test_decode_text_keeps_expressions_for_interpolation() -> None:
    assert decode_text("${seed}", int, path="k") == "${seed}"
    assert decode_text("run-${seed}", str, path="k") == "run-${seed}"
    assert decode_text("${seed},b", tuple[str, ...], path="k") == ["${seed}", "b"]
    assert decode_text("1,${seed}", tuple[int, ...], path="k") == [1, "${seed}"]
    assert decode_text("${oc.create:[1,2]}", tuple[int, ...], path="k") == (
        "${oc.create:[1,2]}"
    )


# -- through compose ----------------------------------------------------------


def test_string_overrides_are_decoded_by_the_leaf_annotation() -> None:
    run = compose_traced(
        schema=RunSpec,
        overrides=[
            "trainer.epochs=7",
            "trainer.out_dir=123",
            "optimizer.betas=0.5,0.6",
            "model.combinator_decoders.fwd.kind=linear",
            "model.combinator_decoders.fwd.bias=off",
        ],
    )
    assert run.value.trainer.epochs == 7
    assert run.value.trainer.out_dir == "123"
    assert run.value.optimizer.betas == (0.5, 0.6)
    assert run.value.model.combinator_decoders["fwd"] == LinearDecoder(bias=False)
    assert subtree(run.tree, "trainer") == {
        "epochs": 7,
        "out_dir": "123",
        "log_dir": "123/logs",
    }
    assert run.provenance["trainer.epochs"].label == "override:trainer.epochs=7"


def test_typed_pairs_are_not_decoded() -> None:
    run = compose_traced(
        schema=RunSpec, overrides=[("trainer.out_dir", "123"), ("trainer.epochs", 3)]
    )
    assert run.value.trainer.out_dir == "123"
    assert run.value.trainer.epochs == 3
    assert run.provenance["trainer.epochs"].label == "override:trainer.epochs=3"
    assert run.provenance["trainer.out_dir"].label == 'override:trainer.out_dir="123"'


def test_json_text_override_sets_a_whole_union_slot() -> None:
    spec = compose(
        schema=RunSpec,
        overrides=[
            'model.combinator_decoders={"fwd": {"kind": "linear", "bias": false}}'
        ],
    )
    assert spec.model.combinator_decoders == {"fwd": LinearDecoder(bias=False)}


def test_load_values_come_after_string_overrides() -> None:
    class App(Settings, RunSpec):
        pass

    app = App.load(overrides=["trainer.epochs=2"], trainer__epochs=9)
    assert app.trainer.epochs == 9
    assert app.__provenance__["trainer.epochs"].label == "override:trainer.epochs=9"
