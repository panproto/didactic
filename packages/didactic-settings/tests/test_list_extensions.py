"""Schema-aware list extension across every composition layer."""

from pathlib import Path
from typing import Literal

import pytest

import didactic.api as dx
from didactic.settings import ConfigError, compose, compose_traced, strict_merge


class Rule(dx.TaggedUnion, discriminator="kind", extra="forbid"):
    """A grammar rule."""


class Application(Rule):
    """Function application in one direction."""

    kind: Literal["application"] = "application"
    direction: Literal["forward", "backward"] = "forward"


class Composition(Rule):
    """Function composition in one direction and order."""

    kind: Literal["composition"] = "composition"
    direction: Literal["forward", "backward"] = "forward"
    order: int = 1


class Grammar(dx.Model, extra="forbid"):
    """A rule inventory with scalar and optional-list controls."""

    order: int = 1
    rules: tuple[Rule, ...] = ()
    optional: tuple[int, ...] | None = None
    seeded: tuple[int, ...] | None = (1,)


class Experiment(dx.Model, extra="forbid"):
    """A grammar mounted as a config-group slot."""

    grammar: Grammar = dx.field(default_factory=Grammar)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_fragment_defaults_then_profile_and_override_append_in_precedence_order(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "rules" / "application.yaml",
        "rules:\n"
        "  - {kind: application, direction: forward}\n"
        "  - {kind: application, direction: backward}\n",
    )
    _write(
        tmp_path / "rules" / "plus-composition.yaml",
        "defaults: [application]\n"
        "rules+:\n"
        "  - {kind: composition, direction: forward, order: 1}\n",
    )
    primary = _write(tmp_path / "run.yaml", "defaults: [rules/plus-composition]\n")
    _write(
        tmp_path / "profiles" / "backward.yaml",
        "rules+:\n  - {kind: composition, direction: backward, order: 1}\n",
    )

    run = compose_traced(
        primary,
        schema=Grammar,
        profile="backward",
        overrides=['rules+=[{"kind":"composition","direction":"forward","order":2}]'],
    )

    assert run.value.rules == (
        Application(direction="forward"),
        Application(direction="backward"),
        Composition(direction="forward", order=1),
        Composition(direction="backward", order=1),
        Composition(direction="forward", order=2),
    )
    assert run.provenance["rules[0]"].label == "defaults:application"
    assert run.provenance["rules[1]"].label == "defaults:application"
    assert run.provenance["rules[2]"].label == "defaults:rules/plus-composition"
    assert run.provenance["rules[3]"].label == "profile:backward"
    assert run.provenance["rules[4]"].label.startswith("override:rules+=")


def test_group_fragment_extends_the_list_from_its_sibling_default(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "grammar" / "application.yaml",
        "rules:\n  - {kind: application, direction: forward}\n",
    )
    _write(
        tmp_path / "grammar" / "plus.yaml",
        "defaults: [application]\n"
        "rules+:\n  - {kind: composition, direction: backward, order: 2}\n",
    )
    primary = _write(tmp_path / "run.yaml", "defaults:\n  - grammar: plus\n")
    run = compose_traced(primary, schema=Experiment)
    assert run.value.grammar.rules == (
        Application(direction="forward"),
        Composition(direction="backward", order=2),
    )
    assert run.provenance["grammar.rules[0]"].label == "group:grammar=application"
    assert run.provenance["grammar.rules[1]"].label == "group:grammar=plus"


def test_prepend_shifts_existing_values_and_their_origins() -> None:
    run = compose_traced(
        schema=Grammar,
        overlays=[
            {"rules": [{"kind": "application", "direction": "forward"}]},
            {"+rules": [{"kind": "composition", "direction": "backward", "order": 2}]},
        ],
    )
    assert run.value.rules == (
        Composition(direction="backward", order=2),
        Application(direction="forward"),
    )
    assert run.provenance["rules[0]"].label == "overlay:#1"
    assert run.provenance["rules[1]"].label == "overlay:#0"


def test_wholesale_higher_write_replaces_all_lower_extensions() -> None:
    run = compose_traced(
        schema=Grammar,
        overlays=[
            {"rules+": [{"kind": "application"}]},
            {"rules+": [{"kind": "composition", "order": 2}]},
            {"rules": [{"kind": "application", "direction": "backward"}]},
        ],
    )
    assert run.value.rules == (Application(direction="backward"),)
    assert run.provenance.paths == (
        "optional",
        "order",
        "rules[0]",
        "seeded[0]",
    )
    assert run.provenance["rules[0]"].label == "overlay:#2"


def test_extension_checks_element_and_target_types_with_layer_and_path() -> None:
    with pytest.raises(ConfigError) as wrong_element:
        compose(
            schema=Grammar,
            overlays=[{"rules+": [{"kind": "composition", "order": "first"}]}],
        )
    assert wrong_element.value.path == "rules[0].order"
    assert "set by overlay:#0" in str(wrong_element.value)

    with pytest.raises(ConfigError) as non_list:
        compose(schema=Grammar, overrides=["order+=[2]"])
    assert non_list.value.path == "order"
    assert "set by override:order+=[2]" in str(non_list.value)


def test_interpolation_inside_an_appended_union_element_is_resolved() -> None:
    run = compose_traced(
        schema=Grammar,
        overlays=[
            {
                "order": 3,
                "rules+": [
                    {
                        "kind": "composition",
                        "direction": "forward",
                        "order": "${order}",
                    }
                ],
            }
        ],
    )
    assert run.value.rules == (Composition(order=3),)
    origin = run.provenance["rules[0]"]
    assert origin.label == "overlay:#0"
    assert origin.expression is not None
    assert "${order}" in origin.expression


def test_extending_unset_optional_lists_starts_from_default_or_empty() -> None:
    run = compose(
        schema=Grammar,
        overlays=[{"optional+": [2], "seeded+": [2]}],
    )
    assert run.optional == (2,)
    assert run.seeded == (1, 2)

    cleared = compose(
        schema=Grammar,
        overlays=[{"seeded": None}, {"seeded+": [3]}],
    )
    assert cleared.seeded == (3,)


def test_whole_list_interpolation_cannot_be_used_as_an_extension() -> None:
    with pytest.raises(ConfigError) as info:
        compose(schema=Grammar, overlays=[{"rules+": "${other}"}])
    assert info.value.path == "rules"
    assert "whole-list interpolation" in str(info.value)


def test_strict_merge_extends_a_typed_tuple_base() -> None:
    merged = strict_merge({"seeded": (1,)}, {"seeded+": [2]}, schema=Grammar)
    assert merged["seeded"] == [1, 2]


def test_exact_alias_ending_in_plus_wins_over_extension_syntax() -> None:
    class Aliased(dx.Model, extra="forbid"):
        values: tuple[int, ...] = dx.field(default=(1,), alias="values+")

    value = compose(schema=Aliased, overlays=[{"values+": [2]}])
    assert value.values == (2,)


def test_fragment_defaults_cycles_are_refused(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", "defaults: [b]\n")
    _write(tmp_path / "b.yaml", "defaults: [a]\n")
    primary = _write(tmp_path / "run.yaml", "defaults: [a]\n")
    with pytest.raises(ConfigError, match="fragment defaults cycle"):
        compose(primary, schema=Grammar)
