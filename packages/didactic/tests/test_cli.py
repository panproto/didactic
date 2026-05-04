"""Tests for the ``didactic`` CLI."""

# Tests directly invoke the private ``_resolve_model`` helper to
# verify error paths around module/class resolution. Tracked in
# panproto/didactic#1.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from didactic.cli._cli import main

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture


def test_no_args_prints_help_and_returns_1(capsys: CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "didactic:" in out


def test_version_prints_versions(capsys: CaptureFixture[str]) -> None:
    rc = main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "didactic" in out
    assert "panproto" in out


def test_targets_lists_protocol_and_grammar_categories(
    capsys: CaptureFixture[str],
) -> None:
    rc = main(["targets"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "custom emitters" in out
    assert "IoRegistry" in out
    assert "AstParserRegistry" in out


def test_registry_list_empty_when_nothing_registered(
    capsys: CaptureFixture[str],
) -> None:
    from didactic.migrations._migrations import clear_registry

    clear_registry()
    rc = main(["registry", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "(empty" in out


def test_schema_show_dumps_spec(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """``schema show`` prints spec and JSON Schema for a real Model."""
    module_path = tmp_path / "test_cli_schema_show.py"
    module_path.write_text(
        "import didactic.api as dx\n\nclass Foo(dx.Model):\n    x: int\n",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        rc = main(["schema", "show", "test_cli_schema_show:Foo"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Foo" in out
        assert "fingerprint" in out
        assert "json_schema" in out
    finally:
        sys.path.remove(str(tmp_path))


def test_check_breaking_exit_code_2_on_breaking_diff(tmp_path: Path) -> None:
    """``didactic check breaking`` exits 2 when a breaking change is detected.

    Runs the CLI in a subprocess so the exit code propagates as
    documented (the in-process ``main`` also returns 2, but the
    subprocess form mirrors the user-visible contract).
    """
    import subprocess

    module_path = tmp_path / "test_cli_breaking.py"
    module_path.write_text(
        "import didactic.api as dx\n"
        "\n"
        "class V1(dx.Model):\n"
        "    id: str\n"
        "    name: str\n"
        "\n"
        "class V2(dx.Model):\n"
        "    id: str\n"
        "    # `name` removed -> breaking\n"
    )
    env = {**__import__("os").environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from didactic.cli._cli import main; raise SystemExit(main())",
            "check",
            "breaking",
            "test_cli_breaking:V1",
            "test_cli_breaking:V2",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    # exit code 0 = compatible, 2 = breaking; we removed a field so breaking
    assert result.returncode == 2, (
        f"expected 2 (breaking), got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "BREAKING" in result.stdout


def test_check_breaking_compatible_returns_0(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A no-op diff (same Model) is compatible: in-process ``main`` returns 0."""
    module_path = tmp_path / "test_cli_compat.py"
    module_path.write_text(
        "import didactic.api as dx\n\nclass M(dx.Model):\n    id: str\n",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        rc = main(
            [
                "check",
                "breaking",
                "test_cli_compat:M",
                "test_cli_compat:M",
            ]
        )
        assert rc == 0
        assert "compatible" in capsys.readouterr().out
    finally:
        sys.path.remove(str(tmp_path))


def test_schema_subcommand_without_action_prints_usage(
    capsys: CaptureFixture[str],
) -> None:
    """Bare ``schema`` (no ``show``) prints the usage line and returns 1."""
    rc = main(["schema"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "schema show" in err


def test_registry_subcommand_without_action_prints_usage(
    capsys: CaptureFixture[str],
) -> None:
    rc = main(["registry"])
    assert rc == 1
    assert "registry list" in capsys.readouterr().err


def test_check_subcommand_without_action_prints_usage(
    capsys: CaptureFixture[str],
) -> None:
    rc = main(["check"])
    assert rc == 1
    assert "check breaking" in capsys.readouterr().err


def test_resolve_model_rejects_missing_colon() -> None:
    from didactic.cli._cli import resolve_model

    with pytest.raises(ValueError, match="module.path:ClassName"):
        resolve_model("just_a_module")


def test_resolve_model_rejects_missing_class(tmp_path: Path) -> None:
    from didactic.cli._cli import resolve_model

    module_path = tmp_path / "test_cli_resolve.py"
    module_path.write_text("x = 1\n")
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(LookupError, match="Missing"):
            resolve_model("test_cli_resolve:Missing")
    finally:
        sys.path.remove(str(tmp_path))


def test_emit_writes_file(tmp_path: Path) -> None:
    """``emit ... --out`` writes the artefact to disk."""
    module_path = tmp_path / "test_cli_emit_module.py"
    module_path.write_text(
        "import didactic.api as dx\n\nclass Bar(dx.Model):\n    y: int\n",
    )
    out_file = tmp_path / "Bar.schema.json"
    sys.path.insert(0, str(tmp_path))
    try:
        rc = main(
            [
                "emit",
                "test_cli_emit_module:Bar",
                "--target",
                "json_schema",
                "--out",
                str(out_file),
            ]
        )
        assert rc == 0
        assert out_file.exists()
        text = out_file.read_text()
        assert "Bar" in text
    finally:
        sys.path.remove(str(tmp_path))
