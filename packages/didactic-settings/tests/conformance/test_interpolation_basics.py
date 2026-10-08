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
    root: dict[str, str] = {}
    assert resolve("\\${not_resolved}", root=root) == "${not_resolved}"


def test_missing_reference_raises() -> None:
    root: dict[str, dict[str, str]] = {"a": {}}
    with pytest.raises(InterpolationError, match="unresolved"):
        resolve("${a.b}", root=root)


def test_two_node_cycle_reports_the_complete_closed_path() -> None:
    root = {"a": "${b}", "b": "${a}"}
    with pytest.raises(InterpolationError, match=r"a -> b -> a") as info:
        resolve("${a}", root=root)
    assert info.value.cycle_path == (("a",), ("b",), ("a",))


def test_long_cycle_reports_every_node_in_traversal_order() -> None:
    root = {"a": "${b}", "b": "${c}", "c": "${a}"}
    with pytest.raises(InterpolationError, match=r"a -> b -> c -> a") as info:
        resolve("${a}", root=root)
    assert info.value.path == ("c",)
    assert info.value.cycle_path == (("a",), ("b",), ("c",), ("a",))


def test_list_index_paths_are_rendered_in_full() -> None:
    root = {"groups": ["${groups[1]}", "${groups[0]}"]}
    with pytest.raises(
        InterpolationError,
        match=r"groups\[0\] -> groups\[1\] -> groups\[0\]",
    ) as info:
        resolve("${groups[0]}", root=root)
    assert info.value.cycle_path == (
        ("groups", 0),
        ("groups", 1),
        ("groups", 0),
    )


def test_relative_cycle_paths_are_rendered_as_absolute_paths() -> None:
    root = {"group": {"left": "${.right}", "right": "${.left}"}}
    with pytest.raises(
        InterpolationError, match=r"group\.left -> group\.right -> group\.left"
    ) as info:
        resolve("${group.left}", root=root)
    assert info.value.cycle_path == (
        ("group", "left"),
        ("group", "right"),
        ("group", "left"),
    )


def test_acyclic_shared_references_remain_accepted() -> None:
    root = {"common": "value", "left": "${common}", "right": "${common}"}
    assert resolve(root, root=root) == {
        "common": "value",
        "left": "value",
        "right": "value",
    }


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
