"""Profiles: a named layer above the file body and below overlays.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

from pathlib import Path

import pytest

from didactic.settings import ConfigError, compose, compose_traced

from ._schemas import RunSpec


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_string_profile_sits_above_the_file_and_below_overlays(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "trainer:\n  epochs: 20\n  out_dir: file\n")
    _write(
        tmp_path / "profiles" / "dev.yaml", "trainer:\n  epochs: 1\n  out_dir: dev\n"
    )
    overlay = _write(tmp_path / "over.yaml", "trainer:\n  out_dir: over\n")
    run = compose_traced(cfg, schema=RunSpec, profile="dev", overlays=[overlay])
    assert run.value.trainer.epochs == 1
    assert run.value.trainer.out_dir == "over"
    p = run.provenance
    assert p["trainer.epochs"].label == "profile:dev"
    assert p["trainer.epochs"].kind == "profile"
    assert p["trainer.epochs"].name == "dev"
    assert p["trainer.epochs"].path == str(tmp_path / "profiles" / "dev.yaml")
    assert p["trainer.out_dir"].label == "overlay:over.yaml"


def test_mapping_profile_is_used_as_given(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "trainer:\n  epochs: 20\n")
    run = compose_traced(cfg, schema=RunSpec, profile={"trainer": {"epochs": 2}})
    assert run.value.trainer.epochs == 2
    origin = run.provenance["trainer.epochs"]
    assert origin.kind == "profile"
    assert origin.name == ""
    assert origin.label == "profile"
    assert origin.path is None


def test_missing_profile_lists_every_path_tried(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "trainer:\n  epochs: 20\n")
    site = tmp_path / "site"
    site.mkdir()
    with pytest.raises(ConfigError) as info:
        compose(cfg, schema=RunSpec, profile="dev", search_path=[site])
    profiles = tmp_path / "profiles"
    site_profiles = site / "profiles"
    assert str(info.value) == (
        "Profile 'dev' not found; tried: "
        f"{profiles / 'dev.yaml'}, {profiles / 'dev.yml'}, {profiles / 'dev.toml'}, "
        f"{profiles / 'dev.json'}, {site_profiles / 'dev.yaml'}, "
        f"{site_profiles / 'dev.yml'}, {site_profiles / 'dev.toml'}, "
        f"{site_profiles / 'dev.json'}"
    )


def test_profile_from_a_later_search_path_root(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "run.yaml", "trainer:\n  epochs: 20\n")
    site = tmp_path / "site"
    _write(site / "profiles" / "long.toml", "[trainer]\nepochs = 100\n")
    run = compose_traced(cfg, schema=RunSpec, profile="long", search_path=[site])
    assert run.value.trainer.epochs == 100
    assert run.provenance["trainer.epochs"].path == str(site / "profiles" / "long.toml")


def test_string_profile_without_any_root_needs_a_config_directory() -> None:
    with pytest.raises(ConfigError, match="needs a config directory"):
        compose(schema=RunSpec, profile="dev")


def test_unknown_key_in_a_profile_is_refused_naming_the_profile(tmp_path: Path) -> None:
    _write(tmp_path / "profiles" / "dev.yaml", "trainer:\n  epoch: 1\n")
    with pytest.raises(ConfigError) as info:
        compose(schema=RunSpec, profile="dev", search_path=[tmp_path])
    assert str(info.value).startswith(
        "Unknown config key 'trainer.epoch' (set by profile:dev)"
    )
