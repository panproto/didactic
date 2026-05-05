"""Tests for ``pathlib.Path`` (and ``PurePath`` family) as field types.

Pydantic accepts ``Path`` natively as a string-shaped field that
round-trips through ``str(p)`` / ``Path(s)``. didactic mirrors that
contract so configuration models migrating across don't have to wrap
every Path-typed field in a property.
"""

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

import didactic.api as dx


class _Cfg(dx.Model):
    data_dir: Path
    pure: PurePosixPath = PurePosixPath("a/b")
    optional_log: Path | None = None


def test_path_field_constructs() -> None:
    c = _Cfg(data_dir=Path("/tmp/x"))
    assert c.data_dir == Path("/tmp/x")
    assert isinstance(c.data_dir, Path)


def test_path_round_trip_through_json() -> None:
    c = _Cfg(data_dir=Path("/tmp/x"), optional_log=Path("/var/log/a.log"))
    payload = c.model_dump_json()
    out = _Cfg.model_validate_json(payload)
    assert out == c
    assert isinstance(out.data_dir, Path)
    assert isinstance(out.optional_log, Path)


def test_pure_path_subclass_round_trips_with_subclass() -> None:
    """``PurePosixPath``-typed field reconstructs as the same subclass."""
    c = _Cfg(data_dir=Path("/tmp/x"))
    assert c.pure == PurePosixPath("a/b")
    assert isinstance(c.pure, PurePosixPath)


def test_pure_windows_path_round_trips() -> None:
    """The path family uses one shared sort, so any ``PurePath`` works."""

    class W(dx.Model):
        p: PureWindowsPath

    w = W(p=PureWindowsPath(r"C:\\tmp"))
    out = W.model_validate_json(w.model_dump_json())
    assert out == w
    assert isinstance(out.p, PureWindowsPath)


def test_path_field_rejects_non_path_input() -> None:
    """Encoder raises ``TypeError`` -> ``ValidationError`` on bad input."""
    with pytest.raises(dx.ValidationError) as exc:
        _Cfg(data_dir=42)  # type: ignore[arg-type]
    assert exc.value.entries[0].loc == ("data_dir",)
    assert exc.value.entries[0].type == "type_error"


def test_purepath_base_classifies() -> None:
    """The base ``PurePath`` (not just subclasses) classifies."""

    class M(dx.Model):
        p: PurePath

    m = M(p=PurePath("a/b"))
    assert m.p == PurePath("a/b")
