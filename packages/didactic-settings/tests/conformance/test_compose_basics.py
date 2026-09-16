"""End-to-end compose pipeline tests against the FakeSchema fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from didactic.settings import ConfigError, compose

from .conftest import FakeNested, FakeSchema


def _write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_minimal_yaml_loads(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path / "cfg.yaml", "name: hello\n")
    config = compose(cfg_path, schema=FakeSchema)
    assert config.name == "hello"


def test_profile_dict_merged_first(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path / "cfg.yaml", "name: from_yaml\n")
    config = compose(
        cfg_path,
        schema=FakeSchema,
        base={"name": "from_profile", "enabled": True},
    )
    assert config.name == "from_yaml"  # YAML beats profile
    assert config.enabled is True


def test_overrides_take_precedence(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path / "cfg.yaml", "name: yaml\n")
    config = compose(
        cfg_path,
        schema=FakeSchema,
        overrides=["name=cli"],
    )
    assert config.name == "cli"


def test_override_typed_value(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path / "cfg.yaml", "nested:\n  count: 1\n")
    config = compose(
        cfg_path,
        schema=FakeSchema,
        overrides=["nested.count=42"],
    )
    assert config.nested.count == 42


def test_strict_unknown_key_raises(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path / "cfg.yaml", "not_a_real_key: 5\n")
    with pytest.raises(ConfigError, match="Unknown config key"):
        compose(cfg_path, schema=FakeSchema)


def test_strict_unknown_nested_key_raises(tmp_path: Path) -> None:
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        "nested:\n  not_a_real_subkey: 5\n",
    )
    with pytest.raises(ConfigError, match="nested.not_a_real_subkey"):
        compose(cfg_path, schema=FakeSchema)


def test_defaults_list_merges_left_to_right(tmp_path: Path) -> None:
    base = _write_yaml(tmp_path / "base.yaml", "name: base\nenabled: true\n")
    middle = _write_yaml(tmp_path / "middle.yaml", "name: middle\n")
    primary = _write_yaml(
        tmp_path / "primary.yaml",
        f"defaults:\n  - {base.stem}\n  - {middle.stem}\nname: final\n",
    )
    config = compose(primary, schema=FakeSchema)
    assert config.name == "final"
    assert config.enabled is True


def test_defaults_list_without_extension(tmp_path: Path) -> None:
    _write_yaml(tmp_path / "base.yaml", "name: base\n")
    primary = _write_yaml(tmp_path / "primary.yaml", "defaults:\n  - base\n")
    config = compose(primary, schema=FakeSchema)
    assert config.name == "base"


def test_extra_overlays(tmp_path: Path) -> None:
    primary = _write_yaml(tmp_path / "primary.yaml", "name: A\n")
    overlay = _write_yaml(tmp_path / "overlay.yaml", "name: B\n")
    config = compose(
        primary,
        schema=FakeSchema,
        overlays=[overlay],
    )
    assert config.name == "B"


def test_toml_supported(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text('name = "from_toml"\n', encoding="utf-8")
    config = compose(cfg_path, schema=FakeSchema)
    assert config.name == "from_toml"


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    bad = tmp_path / "cfg.xml"
    bad.write_text("<xml/>", encoding="utf-8")
    with pytest.raises(ConfigError, match="Unsupported"):
        compose(bad, schema=FakeSchema)


def test_interpolation_resolves_against_composed_root(tmp_path: Path) -> None:
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        "paths:\n  data_dir: /tmp/x\n  out_dir: ${paths.data_dir}/out\n",
    )
    config = compose(cfg_path, schema=FakeSchema)
    assert config.paths["out_dir"] == "/tmp/x/out"


def test_env_interpolation_in_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEAD_DATA", "/data/from/env")
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        "paths:\n  data_dir: ${oc.env:BEAD_DATA}\n",
    )
    config = compose(cfg_path, schema=FakeSchema)
    assert config.paths["data_dir"] == "/data/from/env"


def test_no_config_path_uses_profile_and_overrides() -> None:
    config = compose(
        schema=FakeSchema,
        base={"name": "P"},
        overrides=["nested.count=3"],
    )
    assert config.name == "P"
    assert config.nested.count == 3


def test_bad_override_no_equals() -> None:
    with pytest.raises(ConfigError, match="missing '='"):
        compose(schema=FakeSchema, overrides=["no_equals_here"])


def test_resolved_root_must_be_mapping(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text("name = 'ok'\n", encoding="utf-8")
    # FakeSchema requires a top-level mapping; this is the happy case.
    config = compose(cfg_path, schema=FakeSchema)
    assert isinstance(config, FakeSchema)
    _ = FakeNested  # imported for test isolation typing
