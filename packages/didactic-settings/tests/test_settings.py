"""Tests for didactic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from didactic.settings import (
    CliSource,
    DotEnvSource,
    EnvSource,
    FileSource,
    Settings,
)

# -- env source -------------------------------------------------------


def test_env_source_reads_prefixed_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "9090")
    monkeypatch.setenv("APP_DEBUG", "true")

    class App(Settings):
        port: int = 8080
        debug: bool = False
        __sources__: ClassVar = (EnvSource(prefix="APP_"),)

    s = App.load()
    assert s.port == 9090
    assert s.debug is True
    assert s.__provenance__["port"] == "env"
    assert s.__provenance__["debug"] == "env"


def test_env_source_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_PORT", raising=False)

    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (EnvSource(prefix="APP_"),)

    s = App.load()
    assert s.port == 8080
    assert s.__provenance__["port"] == "default"


# -- dotenv source ----------------------------------------------------


def test_dotenv_source_reads_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=7070\nDEBUG=yes\n")

    class App(Settings):
        port: int = 8080
        debug: bool = False
        __sources__: ClassVar = (DotEnvSource(path=str(env_file)),)

    s = App.load()
    assert s.port == 7070
    assert s.debug is True
    assert s.__provenance__["port"] == "dotenv"


# -- file source ------------------------------------------------------


def test_file_source_reads_json(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text('{"port": 6060, "debug": true}')

    class App(Settings):
        port: int = 8080
        debug: bool = False
        __sources__: ClassVar = (FileSource(path=str(cfg)),)

    s = App.load()
    assert s.port == 6060
    assert s.debug is True


def test_file_source_reads_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("port = 5050\ndebug = true\n")

    class App(Settings):
        port: int = 8080
        debug: bool = False
        __sources__: ClassVar = (FileSource(path=str(cfg)),)

    s = App.load()
    assert s.port == 5050


def test_file_source_missing_file_is_no_op(tmp_path: Path) -> None:
    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (FileSource(path=str(tmp_path / "nope.json")),)

    s = App.load()
    assert s.port == 8080
    assert s.__provenance__["port"] == "default"


# -- cli source -------------------------------------------------------


def test_cli_source_reads_namespace() -> None:
    import argparse

    ns = argparse.Namespace(port=4040, debug=False)

    class App(Settings):
        port: int = 8080
        debug: bool = False
        __sources__: ClassVar = (CliSource(args=ns),)

    s = App.load()
    assert s.port == 4040
    assert s.__provenance__["port"] == "cli"


def test_cli_source_reads_dict() -> None:
    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (CliSource(args={"port": 3030}),)

    s = App.load()
    assert s.port == 3030


def test_cli_source_skips_none_values() -> None:
    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (CliSource(args={"port": None}),)

    s = App.load()
    assert s.port == 8080  # falls through to default


# -- precedence -------------------------------------------------------


def test_later_source_overrides_earlier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APP_PORT", "1111")
    cfg = tmp_path / "config.json"
    cfg.write_text('{"port": 2222}')

    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (
            EnvSource(prefix="APP_"),
            FileSource(path=str(cfg)),
        )

    s = App.load()
    assert s.port == 2222  # file wins; declared after env
    assert s.__provenance__["port"] == "file"


def test_load_kwargs_have_final_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_PORT", "1111")

    class App(Settings):
        port: int = 8080
        __sources__: ClassVar = (EnvSource(prefix="APP_"),)

    s = App.load(port=9999)
    assert s.port == 9999
    assert s.__provenance__["port"] == "override"
