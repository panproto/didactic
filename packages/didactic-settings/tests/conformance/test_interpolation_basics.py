"""Core interpolation grammar: absolute and relative references,
list indexing, type preservation, escapes, cycles."""

from __future__ import annotations

import pytest

from didactic.settings import InterpolationError, resolve


def test_absolute_reference_string() -> None:
    root = {"paths": {"data_dir": "/tmp/bead"}}
    assert resolve("${paths.data_dir}", root=root) == "/tmp/bead"


def test_absolute_reference_typed() -> None:
    """Standalone ${...} preserves the referenced value's type."""
    root = {"counts": {"n": 7}}
    assert resolve("${counts.n}", root=root) == 7
    assert isinstance(resolve("${counts.n}", root=root), int)


def test_substring_substitution_coerces_to_str() -> None:
    root = {"counts": {"n": 7}}
    assert resolve("you have ${counts.n} items", root=root) == "you have 7 items"


def test_relative_reference_one_up() -> None:
    """${.x} resolves against the parent of the current node."""
    root = {"section": {"x": "value", "ref": "${.x}"}}
    out = resolve(root, root=root)
    assert isinstance(out, dict)
    section = out["section"]
    assert isinstance(section, dict)
    assert section["ref"] == "value"


def test_relative_reference_two_up() -> None:
    root = {
        "a": {
            "b": {"ref": "${..target}"},
            "target": "found",
        }
    }
    out = resolve(root, root=root)
    assert isinstance(out, dict)
    a = out["a"]
    assert isinstance(a, dict)
    b = a["b"]
    assert isinstance(b, dict)
    assert b["ref"] == "found"


def test_list_indexing_bracketed() -> None:
    root = {"items": ["zero", "one", "two"]}
    assert resolve("${items[1]}", root=root) == "one"


def test_list_indexing_dotted() -> None:
    root = {"items": ["zero", "one", "two"]}
    assert resolve("${items.2}", root=root) == "two"


def test_nested_interpolation() -> None:
    """The inner ${...} is resolved first, then spliced into the outer path."""
    root = {"which": "alpha", "alpha": "value-A", "beta": "value-B"}
    assert resolve("${${which}}", root=root) == "value-A"


def test_escape_literal_dollar_brace() -> None:
    """\\${literal} produces a literal ${literal}."""
    root: dict = {}
    assert resolve("\\${not_resolved}", root=root) == "${not_resolved}"


def test_missing_reference_raises() -> None:
    root = {"a": {}}
    with pytest.raises(InterpolationError, match="unresolved"):
        resolve("${a.b}", root=root)


def test_cycle_detection() -> None:
    root = {"a": "${b}", "b": "${a}"}
    with pytest.raises(InterpolationError, match="cycle"):
        resolve("${a}", root=root)


def test_relative_above_root_raises() -> None:
    root = {"x": "${..y}"}
    with pytest.raises(InterpolationError, match="above the root"):
        resolve(root, root=root)


def test_dict_value_resolves_recursively() -> None:
    root = {
        "paths": {"data_dir": "/tmp"},
        "out": {"items": "${paths.data_dir}/items"},
    }
    out = resolve(root, root=root)
    assert isinstance(out, dict)
    out_section = out["out"]
    assert isinstance(out_section, dict)
    assert out_section["items"] == "/tmp/items"


def test_concatenation_with_multiple_interpolations() -> None:
    root = {"a": "X", "b": "Y"}
    assert resolve("[${a}_${b}]", root=root) == "[X_Y]"


def test_list_index_out_of_range() -> None:
    root = {"items": ["a"]}
    with pytest.raises(InterpolationError, match="out of range"):
        resolve("${items[5]}", root=root)


def test_dict_indexed_with_integer_raises() -> None:
    root = {"section": {"foo": "bar"}}
    with pytest.raises(InterpolationError, match="dict"):
        resolve("${section[0]}", root=root)
