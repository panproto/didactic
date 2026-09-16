"""Document loading and fragment lookup across the search roots."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from didactic.settings import ConfigError, MissingFragmentError, load_document
from didactic.settings._documents import (
    SUFFIXES,
    candidate_paths,
    find_fragment,
    find_profile,
    list_stems,
    locate,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_document_dispatches_on_the_suffix(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"a": {"b": 1}, "c": [true, null]}')
    (tmp_path / "a.toml").write_text("[a]\nb = 1\n")
    (tmp_path / "a.yaml").write_text("a:\n  b: 1\nc: [true, null]\n")
    (tmp_path / "a.yml").write_text("a: {b: 1}\n")
    assert load_document(tmp_path / "a.json") == {"a": {"b": 1}, "c": [True, None]}
    assert load_document(tmp_path / "a.toml") == {"a": {"b": 1}}
    assert load_document(tmp_path / "a.yaml") == {"a": {"b": 1}, "c": [True, None]}
    assert load_document(str(tmp_path / "a.yml")) == {"a": {"b": 1}}
    assert load_document(tmp_path / "A.JSON".lower()) == {
        "a": {"b": 1},
        "c": [True, None],
    }


def test_load_document_upper_case_suffix(tmp_path: Path) -> None:
    (tmp_path / "up.TOML").write_text("x = 1\n")
    assert load_document(tmp_path / "up.TOML") == {"x": 1}


@pytest.mark.parametrize("name", ["e.json", "e.toml", "e.yaml"])
def test_load_document_empty_file_is_an_empty_document(
    tmp_path: Path, name: str
) -> None:
    (tmp_path / name).write_text("")
    assert load_document(tmp_path / name) == {}
    (tmp_path / name).write_text("   \n")
    assert load_document(tmp_path / name) == {}


@pytest.mark.parametrize(
    ("name", "text", "kind"),
    [
        ("l.json", "[1, 2]", "list"),
        ("l.yaml", "- 1\n- 2\n", "list"),
        ("s.json", '"text"', "str"),
        ("s.yaml", "3\n", "int"),
    ],
)
def test_load_document_non_mapping_root(
    tmp_path: Path, name: str, text: str, kind: str
) -> None:
    (tmp_path / name).write_text(text)
    with pytest.raises(ConfigError) as info:
        load_document(tmp_path / name)
    assert str(info.value) == (
        f"Top-level config in {tmp_path / name} must be a mapping; got {kind}"
    )


def test_load_document_unsupported_suffix(tmp_path: Path) -> None:
    (tmp_path / "x.ini").write_text("[a]\n")
    with pytest.raises(ConfigError) as info:
        load_document(tmp_path / "x.ini")
    assert str(info.value) == (
        f"Unsupported config suffix '.ini' for {tmp_path / 'x.ini'}; "
        "expected .json, .toml, .yaml or .yml"
    )


def test_load_document_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as info:
        load_document(tmp_path / "missing.toml")
    assert (
        str(info.value) == f"Configuration file not found: {tmp_path / 'missing.toml'}"
    )


def test_load_document_stringifies_non_string_yaml_keys(tmp_path: Path) -> None:
    (tmp_path / "k.yaml").write_text("1: one\n2.5: two\nno: three\n")
    assert load_document(tmp_path / "k.yaml") == {
        "1": "one",
        "2.5": "two",
        "False": "three",
    }


# -- fragment lookup ----------------------------------------------------------


def test_candidate_paths_try_each_root_then_each_suffix(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    assert SUFFIXES == (".yaml", ".yml", ".toml", ".json")
    assert candidate_paths("paths", roots=[a, b]) == (
        a / "paths.yaml",
        a / "paths.yml",
        a / "paths.toml",
        a / "paths.json",
        b / "paths.yaml",
        b / "paths.yml",
        b / "paths.toml",
        b / "paths.json",
    )
    assert candidate_paths("sub/paths.toml", roots=[a, b]) == (
        a / "sub" / "paths.toml",
        b / "sub" / "paths.toml",
    )


def test_find_fragment_prefers_the_suffix_order_within_a_root(tmp_path: Path) -> None:
    (tmp_path / "paths.json").write_text("{}")
    assert find_fragment("paths", roots=[tmp_path]) == tmp_path / "paths.json"
    (tmp_path / "paths.toml").write_text("")
    with pytest.raises(ConfigError) as info:
        find_fragment("paths", roots=[tmp_path])
    assert (
        str(info.value)
        == "'defaults' entry 'paths' is ambiguous: paths.json, paths.toml"
    )
    assert find_fragment("paths.json", roots=[tmp_path]) == tmp_path / "paths.json"


def test_find_fragment_earlier_root_shadows_later(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "paths.yaml").write_text("")
    assert find_fragment("paths", roots=[first, second]) == second / "paths.yaml"
    (first / "paths.json").write_text("{}")
    assert find_fragment("paths", roots=[first, second]) == first / "paths.json"
    assert locate("paths", roots=[second, first], subject="x") == second / "paths.yaml"
    assert locate("nope", roots=[first, second], subject="x") is None


def test_find_fragment_missing_lists_every_path_tried(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with pytest.raises(MissingFragmentError) as info:
        find_fragment("base", roots=[first, second])
    e = info.value
    assert e.group == ""
    assert e.name == "base"
    assert e.available == ()
    assert e.tried == candidate_paths("base", roots=[first, second])
    assert str(e) == "'defaults' entry 'base' not found; tried: " + ", ".join(
        str(p) for p in e.tried
    )


def test_find_profile_searches_profiles_under_each_root(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    (second / "profiles").mkdir(parents=True)
    (second / "profiles" / "dev.toml").write_text("")
    (second / "profiles" / "prod.yaml").write_text("")
    (second / "profiles" / "notes.txt").write_text("")
    assert (
        find_profile("dev", roots=[first, second]) == second / "profiles" / "dev.toml"
    )
    with pytest.raises(MissingFragmentError) as info:
        find_profile("stage", roots=[first, second])
    e = info.value
    assert e.group == "profiles"
    assert e.name == "stage"
    assert e.available == ("dev", "prod")
    assert str(e).startswith(
        f"Profile 'stage' not found; tried: {first / 'profiles' / 'stage.yaml'}, "
    )
    assert list_stems([first / "profiles", second / "profiles"]) == ("dev", "prod")
