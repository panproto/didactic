"""The schema-free scalar grammar and the comma splitter."""

from __future__ import annotations

import math

import pytest

from didactic.settings import OverrideSyntaxError, parse_scalar
from didactic.settings._scalars import split_items


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("   ", None),
        ("null", None),
        ("NULL", None),
        ("~", None),
        ("true", True),
        ("True", True),
        ("FALSE", False),
        ("0", 0),
        ("42", 42),
        ("-7", -7),
        ("+3", 3),
        ("1.5", 1.5),
        ("-0.25", -0.25),
        (".5", 0.5),
        ("1.", 1.0),
        ("1e3", 1000.0),
        ("1E-3", 0.001),
        ("2.5e+2", 250.0),
        ("inf", math.inf),
        ("-inf", -math.inf),
        ("[1, 2]", [1, 2]),
        ('["a", {"b": null}]', ["a", {"b": None}]),
        ('{"k": [true, 1.5]}', {"k": [True, 1.5]}),
        ('"quoted"', "quoted"),
        ("'single'", "single"),
        ('"true"', "true"),
        ("bare word", "bare word"),
        ("yes", "yes"),
        ("no", "no"),
        ("on", "on"),
        ("007", "007"),
        ("0x10", "0x10"),
        ("1_000", "1_000"),
        ("  padded  ", "padded"),
    ],
)
def test_parse_scalar_table(text: str, expected: object) -> None:
    assert parse_scalar(text) == expected


def test_parse_scalar_nan_is_a_float() -> None:
    value = parse_scalar("nan")
    assert isinstance(value, float)
    assert math.isnan(value)


@pytest.mark.parametrize("text", ["1", "42", "-3"])
def test_parse_scalar_integers_are_ints_not_floats(text: str) -> None:
    value = parse_scalar(text)
    assert type(value) is int


def test_parse_scalar_refuses_malformed_json_with_the_column() -> None:
    with pytest.raises(OverrideSyntaxError) as info:
        parse_scalar("[1, 2")
    assert str(info.value) == (
        "Value '[1, 2' is not valid JSON: Expecting ',' delimiter at column 6"
    )
    with pytest.raises(OverrideSyntaxError, match="is not valid JSON"):
        parse_scalar("{a: 1}")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a,b,c", ["a", "b", "c"]),
        ("a", ["a"]),
        ("a,", ["a", ""]),
        ("[1,2],3", ["[1,2]", "3"]),
        ('{"k": [1,2]},x', ['{"k": [1,2]}', "x"]),
        ('"x,y",z', ['"x,y"', "z"]),
        ("'x,y',z", ["'x,y'", "z"]),
        ("${oc.select:p,d},e", ["${oc.select:p,d}", "e"]),
        ("${oc.create:[1,2]}", ["${oc.create:[1,2]}"]),
        ("(1,2),3", ["(1,2)", "3"]),
    ],
)
def test_split_items_respects_brackets_braces_and_quotes(
    text: str, expected: list[str]
) -> None:
    assert split_items(text) == expected
