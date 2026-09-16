"""``Settings.load`` over the composition engine: sources as layers.

This module deliberately omits ``from __future__ import annotations``;
see ``_schemas.py``.
"""

from pathlib import Path
from typing import ClassVar

import pytest

import didactic.api as dx
from didactic.settings import (
    CliSource,
    DotEnvSource,
    EnvSource,
    FileSource,
    Provenance,
    Settings,
    UnknownKeyError,
    provenance_of,
)

from ._schemas import LinearDecoder, LstmEncoder, RunSpec, TransformerEncoder


class RunSettings(Settings, RunSpec):
    """The worked example's settings form."""

    __sources__: ClassVar = (EnvSource(prefix="LOFI_"),)


def test_env_source_sets_nested_leaves_by_double_underscore_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOFI_TRAINER__EPOCHS", "5")
    monkeypatch.setenv("LOFI_PATHS__DATA_DIR", "/d")
    s = RunSettings.load()
    assert s.trainer.epochs == 5
    assert s.paths == {"data_dir": "/d"}
    assert isinstance(s.__provenance__, Provenance)
    assert s.__provenance__["trainer.epochs"].label == "source:env"
    assert s.__provenance__["trainer.epochs"].kind == "source"
    assert s.__provenance__["trainer.epochs"].name == "env"
    assert s.__provenance__["paths.data_dir"].label == "source:env"
    assert provenance_of(s) is s.__provenance__


def test_env_source_selects_a_variant_then_sets_its_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOFI_MODEL__TYPE_ENCODER__KIND", "lstm")
    monkeypatch.setenv("LOFI_MODEL__TYPE_ENCODER__HIDDEN", "64")
    s = RunSettings.load()
    assert s.model.type_encoder == LstmEncoder(hidden=64)
    assert s.__provenance__["model.type_encoder.kind"].label == "source:env"


def test_env_source_sets_a_whole_union_slot_and_a_map_slot_from_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOFI_MODEL__TYPE_ENCODER", '{"kind": "lstm", "hidden": 3}')
    monkeypatch.setenv(
        "LOFI_MODEL__COMBINATOR_DECODERS", '{"fwd": {"kind": "linear", "bias": false}}'
    )
    monkeypatch.setenv("LOFI_PATHS", '{"data_dir": "/d", "cache": "/c"}')
    s = RunSettings.load()
    assert s.model.type_encoder == LstmEncoder(hidden=3)
    assert s.model.combinator_decoders == {"fwd": LinearDecoder(bias=False)}
    assert s.paths == {"data_dir": "/d", "cache": "/c"}
    assert s.__provenance__["model.combinator_decoders.fwd.bias"].label == "source:env"
    assert s.__provenance__["paths.cache"].label == "source:env"


def test_env_source_never_looks_up_unrelated_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the source looks up the schema's own paths, so a prefixed variable
    # that names no path is neither read nor refused
    monkeypatch.setenv("LOFI_HOME", "/home")
    monkeypatch.setenv("LOFI_TRAINER__EPOCHS", "2")
    s = RunSettings.load()
    assert s.trainer.epochs == 2
    assert "home" not in s.__provenance__
    assert all(
        o.kind != "source" or p.startswith("trainer.")
        for p, o in s.__provenance__.items()
    )


def test_env_source_unknown_nested_leaf_is_refused_naming_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOFI_MODEL__TYPE_ENCODER__KIND", "transformer")
    monkeypatch.setenv("LOFI_MODEL__TYPE_ENCODER__HIDDEN", "3")
    with pytest.raises(UnknownKeyError) as info:
        RunSettings.load()
    assert info.value.path == "model.type_encoder.hidden"
    assert info.value.declared_by == ("lstm",)
    assert info.value.set_by is not None
    assert info.value.set_by.label == "source:env"


def test_dotenv_source_reads_export_lines_and_nested_paths(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nexport APP_TRAINER__EPOCHS=7\nAPP_TRAINER__OUT_DIR='quoted dir'\n"
    )

    class App(Settings, RunSpec):
        __sources__: ClassVar = (DotEnvSource(path=env_file, prefix="APP_"),)

    s = App.load()
    assert s.trainer.epochs == 7
    assert s.trainer.out_dir == "quoted dir"
    assert s.__provenance__["trainer.epochs"].label == "source:dotenv"


def test_file_source_refuses_unknown_top_level_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "local.toml"
    cfg.write_text("bogus = 1\n")

    class App(Settings, RunSpec):
        __sources__: ClassVar = (FileSource(cfg),)

    with pytest.raises(UnknownKeyError) as info:
        App.load()
    assert info.value.path == "bogus"
    assert info.value.set_by is not None
    assert info.value.set_by.label == "source:file"


def test_file_source_required_raises_when_missing(tmp_path: Path) -> None:
    class App(Settings, RunSpec):
        __sources__: ClassVar = (FileSource(tmp_path / "nope.toml", required=True),)

    with pytest.raises(FileNotFoundError):
        App.load()

    class Lenient(Settings, RunSpec):
        __sources__: ClassVar = (FileSource(tmp_path / "nope.toml"),)

    assert Lenient.load().trainer.epochs == 1


def test_file_source_body_ignores_no_defaults_list(tmp_path: Path) -> None:
    # only the primary ``path`` honours ``defaults:``; a FileSource body that
    # carries one is refused like any other unknown key
    cfg = tmp_path / "local.yaml"
    cfg.write_text("defaults:\n  - paths\ntrainer:\n  epochs: 2\n")

    class App(Settings, RunSpec):
        __sources__: ClassVar = (FileSource(cfg),)

    with pytest.raises(UnknownKeyError) as info:
        App.load()
    assert info.value.path == "defaults"


def test_cli_source_reads_dotted_and_double_underscore_keys() -> None:
    import argparse

    ns = argparse.Namespace(trainer__epochs=4, **{"paths.data_dir": "/d"}, skipped=None)

    class App(Settings, RunSpec):
        __sources__: ClassVar = (CliSource(args=ns),)

    s = App.load()
    assert s.trainer.epochs == 4
    assert s.paths == {"data_dir": "/d"}
    assert s.__provenance__["trainer.epochs"].label == "source:cli"
    assert "skipped" not in s.__provenance__


def test_sources_sit_above_overlays_and_below_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOFI_TRAINER__EPOCHS", "5")
    monkeypatch.setenv("LOFI_TRAINER__OUT_DIR", "env")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "dev.yaml").write_text(
        "trainer:\n  epochs: 1\n  out_dir: dev\n"
    )
    cfg = tmp_path / "run.yaml"
    cfg.write_text("trainer:\n  epochs: 20\n")
    s = RunSettings.load(
        cfg,
        profile="dev",
        overlays=[{"trainer": {"out_dir": "overlay", "log_dir": "overlay/logs"}}],
        trainer__epochs=9,
    )
    assert s.trainer.epochs == 9
    assert s.trainer.out_dir == "env"
    assert s.trainer.log_dir == "overlay/logs"
    p = s.__provenance__
    assert p["trainer.epochs"].label == "override:trainer.epochs=9"
    assert p["trainer.out_dir"].label == "source:env"
    assert p["trainer.log_dir"].label == "overlay:#0"


def test_load_kwargs_are_typed_dotted_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOFI_TRAINER__EPOCHS", raising=False)
    s = RunSettings.load(
        model__type_encoder__kind="transformer", model__type_encoder__num_heads=8
    )
    assert s.model.type_encoder == TransformerEncoder(num_heads=8)
    assert (
        s.__provenance__["model.type_encoder.num_heads"].label
        == "override:model.type_encoder.num_heads=8"
    )


def test_load_traced_returns_the_composed_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOFI_TRAINER__EPOCHS", "3")
    run = RunSettings.load_traced(trainer__out_dir="o")
    assert isinstance(run.value, RunSettings)
    assert run.value.trainer.epochs == 3
    assert run.provenance is run.value.__provenance__
    assert [layer.origin.label for layer in run.layers] == [
        "source:env",
        'override:trainer.out_dir="o"',
    ]


def test_reserved_load_keyword_as_a_field_name_is_refused_at_class_creation() -> None:
    with pytest.raises(TypeError) as info:
        # ``profile`` collides with ``load``'s keyword; the check reads the
        # class annotations, since ``__field_specs__`` is assigned after
        # ``__init_subclass__`` runs
        class Bad(Settings):
            profile: str = ""

        # the class statement raises; the name is referenced for the checker
        _ = Bad

    assert "profile" in str(info.value)
    assert "alias" in str(info.value)
    for reserved in (
        "path",
        "groups",
        "overlays",
        "overrides",
        "search_path",
        "resolvers",
    ):
        with pytest.raises(TypeError, match=reserved):
            type(
                reserved.title(),
                (Settings,),
                {"__annotations__": {reserved: int}, reserved: 0},
            )


def test_duplicate_source_names_are_refused_at_class_creation(tmp_path: Path) -> None:
    with pytest.raises(TypeError) as info:

        class Bad(Settings):
            x: int = 0
            __sources__: ClassVar = (
                FileSource(tmp_path / "a.toml"),
                FileSource(tmp_path / "b.toml"),
            )

        _ = Bad

    assert (
        str(info.value)
        == "Settings sources must have distinct names; 'file' is used twice"
    )

    class Good(Settings):
        x: int = 0
        __sources__: ClassVar = (
            FileSource(tmp_path / "a.toml", name="a"),
            FileSource(tmp_path / "b.toml", name="b"),
        )

    assert Good.load().x == 0


def test_search_path_prepends_the_first_file_sources_parent(tmp_path: Path) -> None:
    conf = tmp_path / "conf"
    (conf / "profiles").mkdir(parents=True)
    (conf / "profiles" / "dev.toml").write_text("[trainer]\nepochs = 11\n")
    local = conf / "local.toml"
    local.write_text("[trainer]\nout_dir = 'local'\n")

    class App(Settings, RunSpec):
        __sources__: ClassVar = (FileSource(local),)

    s = App.load(profile="dev")
    assert s.trainer.epochs == 11
    assert s.trainer.out_dir == "local"
    assert s.__provenance__["trainer.epochs"].label == "profile:dev"
    assert s.__provenance__["trainer.out_dir"].label == "source:file"


def test_plain_construction_carries_no_provenance() -> None:
    class App(Settings):
        x: int = 0

    with pytest.raises(dx.ValidationError):
        App(y=1)  # type: ignore[call-arg]
    assert not hasattr(App(), "__provenance__")
